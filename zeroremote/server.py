# SPDX-License-Identifier: MIT
"""ZeroRemote: la pantalla del Cardputer Zero en el navegador, su teclado, y archivos.

Un servidor HTTP + WebSocket con asyncio, sin dependencias. Sólo escucha en la IP de
Tailscale del aparato (y rechaza cualquier cliente de fuera de 100.64.0.0/10): quien llega
ya ha pasado por la red de Tailscale de Bruno, y en una wifi ajena nadie lo ve.

Lo que está encendido lo deciden los interruptores de la app «Remote» (config.py): con los
dos apagados no escucha en la red. Mientras no hay nadie conectado no lee la pantalla ni gasta
nada: duerme en accept().
"""

import argparse
import asyncio
import ipaddress
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.parse

from . import __version__, config, files, keys, screen, ws

PORT = 8320
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
TAILNET = ipaddress.ip_network("100.64.0.0/10")
# Lo que se sirve tal cual de web/ (nada más: ni listados ni rutas con «..»).
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/favicon.ico": ("icon-32.png", "image/png"),
    "/icon-32.png": ("icon-32.png", "image/png"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/apple-touch-icon.png": ("icon-180.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}


REASONS = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
           411: "Length Required", 500: "Internal Server Error", 507: "Insufficient Storage"}
CHUNK = 64 * 1024


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


# --- Estado del aparato ---

def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def find_battery(root: str = "/sys/class/power_supply") -> str:
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if _read(os.path.join(root, name, "type")) == "Battery":
            return os.path.join(root, name)
    return ""


def device_status(battery: str, backlight: str) -> dict:
    def num(path):
        try:
            return int(_read(path))
        except ValueError:
            return None

    current = num(os.path.join(battery, "current_now")) if battery else None
    return {
        "t": "status",
        "battery": num(os.path.join(battery, "capacity")) if battery else None,
        "charging": _read(os.path.join(battery, "status")) == "Charging" if battery else None,
        # µA, negativo al descargar (bq27220) → mA que gasta, positivo
        "draw_ma": round(-current / 1000) if current is not None else None,
        "brightness": num(os.path.join(backlight, "brightness")) if backlight else None,
    }


# --- La pantalla, compartida por todos los clientes ---

class ScreenFeed:
    """Lee el framebuffer a `fps` mientras haya clientes; cada cliente lleva su propio
    «lo último que le mandé», así uno lento recibe menos imágenes pero nunca rotas."""

    def __init__(self, fb: str, fps: float):
        self.fb = fb
        self.interval = 1.0 / fps
        self.frame = None
        self.seq = 0
        self.clients = 0
        self.changed = asyncio.Condition()
        self.task = None

    def join(self):
        self.clients += 1
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    def leave(self):
        self.clients -= 1

    async def _run(self):
        while self.clients > 0:
            try:
                frame = screen.read_frame(self.fb)
            except OSError as e:
                log(f"framebuffer: {e}")
                await asyncio.sleep(1)
                continue
            if frame != self.frame:
                async with self.changed:
                    self.frame = frame
                    self.seq += 1
                    self.changed.notify_all()
            await asyncio.sleep(self.interval)
        self.frame = None  # el siguiente que llegue empieza con la pantalla entera

    async def wait_newer(self, seq: int):
        async with self.changed:
            await self.changed.wait_for(lambda: self.seq != seq and self.frame is not None)
            return self.seq, self.frame


# --- Servidor ---

class Server:
    def __init__(self, args):
        self.args = args
        self.home = os.path.expanduser("~")
        self.settings = config.Settings()
        self.screen_clients = {}  # writer → IP, para cortarlos si se apaga la pantalla remota
        self.last_client = ""
        self.feed = ScreenFeed(args.fb, args.fps)
        self.battery = find_battery()
        self.backlight = ""
        bl_root = "/sys/class/backlight"
        if os.path.isdir(bl_root) and os.listdir(bl_root):
            self.backlight = os.path.join(bl_root, sorted(os.listdir(bl_root))[0])
        self.keyboard = None
        try:
            self.keyboard = keys.Keyboard(args.keyboard or keys.find_keyboard())
            log(f"keyboard: {self.keyboard.path}")
        except OSError as e:
            log(f"keyboard: {e} (screen only)")

    def allowed(self, peer) -> bool:
        try:
            ip = ipaddress.ip_address(peer[0])
        except (ValueError, TypeError, IndexError):
            return False
        return ip in TAILNET or ip.is_loopback or self.args.any_client

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        try:
            if not self.allowed(peer):
                log(f"refused (not Tailscale): {peer[0] if peer else '?'}")
                writer.close()
                return
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = request.decode("latin-1").split("\r\n")
            method, target, _ = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            url = urllib.parse.urlsplit(target)
            path = url.path
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
            try:
                await self.route(method, path, query, headers, reader, writer, peer)
            except files.FileError as e:
                await self.reply_json(writer, {"error": e.message}, e.code)
            except OSError as e:
                log(f"{method} {path}: {e}")
                await self.reply_json(writer, {"error": e.strerror or "Error de disco"}, 500)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()

    async def route(self, method, path, query, headers, reader, writer, peer):
        if path == "/ws" and method == "GET" and headers.get("upgrade", "").lower() == "websocket":
            if not self.settings.screen:
                await self.reply(writer, 403, b"Remote screen is off")
            else:
                await self.websocket(reader, writer, headers, peer)
        elif path in STATIC and method == "GET":
            name, ctype = STATIC[path]
            if name == "index.html":
                log(f"page requested: {peer[0]}")
            await self.static(writer, name, ctype)
        elif path == "/api/settings" and method == "POST":
            await self.api_settings(query, writer, peer)
        elif path == "/api/info" and method == "GET":
            await self.reply_json(writer, {"version": __version__, "screen": self.settings.screen,
                                           "files": self.settings.files,
                                           "roots": [{"key": r["key"], "label": r["label"]} for r in files.roots(self.home)]})
        elif path.startswith("/api/"):
            if not self.settings.files:
                raise files.FileError(403, "Compartir archivos está apagado (actívalo en Remote, en el Cardputer)")
            handlers = {
                ("GET", "/api/files"): self.api_list,
                ("GET", "/api/download"): self.api_download,
                ("POST", "/api/upload"): self.api_upload,
                ("POST", "/api/mkdir"): self.api_mkdir,
                ("POST", "/api/delete"): self.api_delete,
            }
            handler = handlers.get((method, path))
            if handler is None:
                raise files.FileError(404, "No existe")
            await handler(query, headers, reader, writer, peer)
        else:
            await self.reply(writer, 404 if method == "GET" else 405, b"Not Found")

    def send_head(self, writer, code: int, ctype: str, length: int, extra: str = ""):
        writer.write(
            f"HTTP/1.1 {code} {REASONS.get(code, '')}\r\nContent-Type: {ctype}\r\nContent-Length: {length}\r\n"
            f"Cache-Control: no-cache\r\n{extra}Connection: close\r\n\r\n".encode()
        )

    async def reply(self, writer, code: int, body: bytes, ctype: str = "text/plain"):
        self.send_head(writer, code, ctype, len(body))
        writer.write(body)
        await writer.drain()

    async def reply_json(self, writer, obj, code: int = 200):
        await self.reply(writer, code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    async def api_settings(self, query, writer, peer):
        """Los interruptores desde la web (los mismos que en la app Remote). Se guardan en su
        fichero y se aplican ya. Con los dos apagados el servicio deja de escuchar: la web lo
        avisa antes, y se vuelve a encender desde la app."""
        new = config.Settings(self.settings.screen, self.settings.files)
        for key in ("screen", "files"):
            value = query.get(key)
            if value not in (None, "on", "off"):
                raise files.FileError(400, "Valor no válido")
            if value is not None:
                setattr(new, key, value == "on")
        config.save(config.config_path(), new)
        log(f"settings from {peer[0]}: screen={'on' if new.screen else 'off'} files={'on' if new.files else 'off'}")
        await self.reply_json(writer, {"screen": new.screen, "files": new.files})
        if not new.screen:
            for w in list(self.screen_clients):
                w.close()
        self.settings = new

    # --- Archivos ---

    def _place(self, query):
        """(carpeta raíz, ruta absoluta) de los parámetros root y path, comprobada."""
        root = files.root_path(self.home, query.get("root", ""))
        os.makedirs(root, exist_ok=True)  # Tracks, por ejemplo, no existe hasta grabar uno
        return root, files.resolve(root, query.get("path", ""))

    async def api_list(self, query, headers, reader, writer, peer):
        root, folder = self._place(query)
        usage = os.statvfs(folder)
        await self.reply_json(writer, {"entries": files.list_dir(folder),
                                       "free": usage.f_bavail * usage.f_frsize})

    async def api_download(self, query, headers, reader, writer, peer):
        root, path = self._place(query)
        if not os.path.isfile(path):
            raise files.FileError(404, "No existe")
        name = os.path.basename(path)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        # inline=1 para verla en el navegador (una foto); si no, se descarga.
        disposition = "inline" if query.get("inline") == "1" else "attachment"
        quoted = urllib.parse.quote(name)
        log(f"download {name} ({size} B) to {peer[0]}")
        with open(path, "rb") as f:
            self.send_head(writer, 200, ctype, size, f"Content-Disposition: {disposition}; filename*=UTF-8''{quoted}\r\n")
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()

    async def api_upload(self, query, headers, reader, writer, peer):
        root, folder = self._place(query)
        if not os.path.isdir(folder):
            raise files.FileError(404, "La carpeta no existe")
        name = files.check_name(query.get("name", ""))
        try:
            length = int(headers.get("content-length", ""))
        except ValueError:
            raise files.FileError(411, "Falta el tamaño")
        files.check_space(folder, length)
        dest = files.unique_path(folder, name)
        part = dest + ".part"  # oculto en los listados; si se corta, se borra
        log(f"upload {os.path.basename(dest)} ({length} B) from {peer[0]}")
        try:
            with open(part, "wb") as f:
                remaining = length
                while remaining > 0:
                    chunk = await asyncio.wait_for(reader.read(min(CHUNK, remaining)), 60)
                    if not chunk:
                        raise asyncio.IncompleteReadError(b"", remaining)
                    f.write(chunk)
                    remaining -= len(chunk)
                    if not self.settings.files:
                        raise files.FileError(403, "Se ha apagado compartir archivos")
            os.replace(part, dest)
        finally:
            if os.path.exists(part):
                os.remove(part)
        await self.reply_json(writer, {"ok": True, "name": os.path.basename(dest)})

    async def api_mkdir(self, query, headers, reader, writer, peer):
        root, folder = self._place(query)
        path = os.path.join(folder, files.check_name(query.get("name", "")))
        if os.path.exists(path):
            raise files.FileError(400, "Ya existe")
        os.mkdir(path)
        await self.reply_json(writer, {"ok": True})

    async def api_delete(self, query, headers, reader, writer, peer):
        root, path = self._place(query)
        log(f"delete {os.path.relpath(path, root)} in {query.get('root')} from {peer[0]}")
        await asyncio.to_thread(files.delete, path, root)
        await self.reply_json(writer, {"ok": True})

    async def static(self, writer, name: str, ctype: str):
        with open(os.path.join(WEB_DIR, name), "rb") as f:
            await self.reply(writer, 200, f.read(), ctype)

    async def websocket(self, reader, writer, headers, peer):
        writer.write(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {ws.accept_key(headers.get('sec-websocket-key', ''))}\r\n\r\n".encode()
        )
        await writer.drain()
        log(f"client connected: {peer[0]}")
        self.screen_clients[writer] = peer[0]
        self.last_client = peer[0]
        pressed = set()  # lo que ha pulsado este cliente, para soltarlo si se va
        status_soon = asyncio.Event()  # tras una tecla, el estado (brillo) enseguida
        self.feed.join()
        sender = asyncio.create_task(self.send_loop(writer, status_soon))
        try:
            await self.receive_loop(reader, writer, pressed, status_soon)
        finally:
            sender.cancel()
            self.feed.leave()
            self.screen_clients.pop(writer, None)
            if self.keyboard:
                for code in pressed:
                    self.keyboard.set(code, False)
            log(f"client gone: {peer[0]}")

    async def send_loop(self, writer, status_soon):
        seq, last = 0, None
        next_status = 0.0
        try:
            while True:
                try:
                    seq, frame = await asyncio.wait_for(self.feed.wait_newer(seq), 0.5)
                except asyncio.TimeoutError:
                    frame = None
                if status_soon.is_set():
                    status_soon.clear()
                    next_status = 0.0
                if frame is not None:
                    bands = screen.changed_bands(last, frame)
                    for y, rows in bands:
                        writer.write(ws.encode_frame(screen.encode_band(frame, y, rows), ws.OP_BINARY))
                    if bands:
                        writer.write(ws.encode_frame(screen.FRAME_END, ws.OP_BINARY))
                    last = frame
                now = time.monotonic()
                if now >= next_status:
                    next_status = now + 3
                    status = device_status(self.battery, self.backlight)
                    writer.write(ws.encode_frame(json.dumps(status).encode(), ws.OP_TEXT))
                # Si la red no da abasto, esto espera: el cliente lento salta imágenes.
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    async def _tap(self, code: int, after: float):
        self.keyboard.set(code, True)
        await asyncio.sleep(0.04)
        self.keyboard.set(code, False)
        await asyncio.sleep(after)

    async def wake(self, unlock: bool = False):
        """Despierta la pantalla con Mayúsculas (no hace nada en las apps). El salvapantallas
        del lanzador a veces no enciende con la primera pulsación y sí con la segunda: se
        comprueba el brillo y se reintenta.

        Con `unlock`, si lo que se ve es la pantalla de bloqueo del lanzador (su aviso
        amarillo), manda TAB y ENTER, que es como se desbloquea. Sólo entonces: con la
        pantalla apagada dentro de una app, TAB y ENTER harían cosas en la app. Hasta tres
        tandas: si el bloqueo estaba esperando el ENTER, la primera TAB lo devuelve al
        principio y hace falta otra."""
        for _ in range(3):
            if device_status("", self.backlight)["brightness"] != 0:
                break
            await self._tap(keys.KEY_LEFTSHIFT, 0)
            for _ in range(12):
                await asyncio.sleep(0.1)
                if device_status("", self.backlight)["brightness"] != 0:
                    break
        if not unlock:
            return
        await asyncio.sleep(0.4)  # que el lanzador pinte el aviso
        for attempt in range(3):
            try:
                frame = screen.read_frame(self.args.fb)
            except OSError:
                return
            if not screen.is_lockscreen(frame):
                if attempt:
                    log("unlocked")
                return
            log("lock screen: TAB + ENTER")
            await self._tap(keys.KEY_TAB, 0.35)
            await self._tap(keys.KEY_ENTER, 0.7)

    async def touch(self, x: float):
        """Un toque en la imagen de la web, `x` de 0 (izquierda) a 1 (derecha).

        Apagada o bloqueada: despertar y desbloquear. En la pantalla de inicio del lanzador,
        tocar a un lado es como su flecha de ese lado (las «‹ ›» que pinta el carrusel) y en el
        centro, ENTER: abre la app seleccionada. En cualquier otra pantalla no se manda nada:
        dentro de una app una flecha o un ENTER harían cosas."""
        dark = device_status("", self.backlight)["brightness"] == 0
        try:
            frame = None if dark else screen.read_frame(self.args.fb)
        except OSError:
            return
        if dark or screen.is_lockscreen(frame):
            await self.wake(unlock=True)
        elif screen.is_launcher_home(frame):
            await self._tap(keys.KEY_LEFT if x < 0.25 else keys.KEY_RIGHT if x > 0.75 else keys.KEY_ENTER, 0)

    async def receive_loop(self, reader, writer, pressed, status_soon):
        while True:
            try:
                opcode, payload = await ws.read_frame(reader)
            except (ws.ProtocolError, asyncio.IncompleteReadError, ConnectionError):
                return
            if opcode == ws.OP_CLOSE:
                writer.write(ws.encode_frame(b"", ws.OP_CLOSE))
                return
            if opcode == ws.OP_PING:
                writer.write(ws.encode_frame(payload, ws.OP_PONG))
                continue
            if opcode != ws.OP_TEXT:
                continue
            try:
                msg = json.loads(payload)
                code = int(msg.get("code", 0))
            except (ValueError, AttributeError, TypeError):
                continue
            if not self.keyboard:
                continue
            status_soon.set()
            if msg.get("t") == "wake":
                await self.wake(unlock=bool(msg.get("unlock")))
            elif msg.get("t") == "touch":
                try:
                    x = min(max(float(msg.get("x", 0.5)), 0.0), 1.0)
                except (TypeError, ValueError):
                    x = 0.5
                await self.touch(x)
                status_soon.set()
            elif msg.get("t") == "key":
                down = bool(msg.get("down"))
                self.keyboard.set(code, down)
                (pressed.add if down else pressed.discard)(code)
            elif msg.get("t") == "tap" and code not in pressed:
                self.keyboard.set(code, True)
                await asyncio.sleep(0.04)
                self.keyboard.set(code, False)


def tailscale_ip(timeout_s: float = 0) -> str:
    """La IP de Tailscale del aparato; espera a que Tailscale arranque si hace falta."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10).stdout
            ip = out.split()[0] if out.split() else ""
            if ip:
                return ip
        except (OSError, subprocess.TimeoutExpired):
            pass
        if time.monotonic() >= deadline:
            return ""
        time.sleep(5)


async def main_async(args):
    """Vigila los interruptores cada 2 s: abre o cierra el puerto, corta a quien ya no toca y
    deja el estado para la app."""
    server = Server(args)
    conf_path = config.config_path()
    status_path = config.status_path()
    conf_mtime = None
    srv = None
    hosts = []
    while True:
        m = config.mtime(conf_path)
        if m != conf_mtime:
            conf_mtime = m
            new = config.load(conf_path)
            if new != server.settings:
                log(f"settings: screen={'on' if new.screen else 'off'} files={'on' if new.files else 'off'}")
            if not new.screen:
                for w in list(server.screen_clients):
                    w.close()  # la pantalla remota se ha apagado: fuera los que miraban
            server.settings = new

        if server.settings.any and srv is None:
            hosts = [h for h in (args.listen or [await asyncio.to_thread(tailscale_ip)]) if h]
            if hosts:
                try:
                    srv = await asyncio.start_server(server.handle, hosts, args.port)
                    log("listening on " + ", ".join(f"http://{h}:{args.port}/" for h in hosts))
                except OSError as e:
                    log(f"cannot listen: {e}")
        elif not server.settings.any and srv is not None:
            srv.close()
            for w in list(server.screen_clients):
                w.close()
            srv = None
            log("both off: not listening")

        try:
            config.write_status(status_path, {
                "listening": 1 if srv else 0,
                "url": f"http://{hosts[0]}:{args.port}/" if srv and hosts else "",
                "screen": "on" if server.settings.screen else "off",
                "files": "on" if server.settings.files else "off",
                "clients": len(server.screen_clients),
                "last_client": server.last_client,
            })
        except OSError as e:
            log(f"status: {e}")
        await asyncio.sleep(2)


def main(argv=None):
    p = argparse.ArgumentParser(prog="zeroremote", description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--listen", action="append", help="address to listen on (default: the Tailscale IP)")
    p.add_argument("--fps", type=float, default=20.0, help="screen reads per second while someone is watching")
    p.add_argument("--fb", default="/dev/fb0")
    p.add_argument("--keyboard", help="input device (default: the first real keyboard)")
    p.add_argument("--any-client", action="store_true", help="accept clients outside Tailscale (testing only)")
    args = p.parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass
