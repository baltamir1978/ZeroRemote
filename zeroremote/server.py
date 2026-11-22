# SPDX-License-Identifier: MIT
"""ZeroRemote: la pantalla del Cardputer Zero en el navegador, y su teclado.

Un servidor HTTP + WebSocket con asyncio, sin dependencias. Sólo escucha en la IP de
Tailscale del aparato (y rechaza cualquier cliente de fuera de 100.64.0.0/10): quien llega
ya ha pasado por la red de Tailscale de Bruno, y en una wifi ajena nadie lo ve.

Mientras no hay nadie conectado no lee la pantalla ni gasta nada: duerme en accept().
"""

import argparse
import asyncio
import ipaddress
import json
import os
import subprocess
import sys
import time

from . import keys, screen, ws

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
            method, path, _ = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if method != "GET":
                await self.reply(writer, 405, b"Method Not Allowed")
            elif path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
                await self.websocket(reader, writer, headers, peer)
            elif path.split("?")[0] in STATIC:
                name, ctype = STATIC[path.split("?")[0]]
                if name == "index.html":
                    log(f"page requested: {peer[0]}")
                await self.static(writer, name, ctype)
            else:
                await self.reply(writer, 404, b"Not Found")
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()

    async def reply(self, writer, code: int, body: bytes, ctype: str = "text/plain"):
        reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(code, "")
        writer.write(
            f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
            "Cache-Control: no-cache\r\nConnection: close\r\n\r\n".encode() + body
        )
        await writer.drain()

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
        pressed = set()  # lo que ha pulsado este cliente, para soltarlo si se va
        status_soon = asyncio.Event()  # tras una tecla, el estado (brillo) enseguida
        self.feed.join()
        sender = asyncio.create_task(self.send_loop(writer, status_soon))
        try:
            await self.receive_loop(reader, writer, pressed, status_soon)
        finally:
            sender.cancel()
            self.feed.leave()
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
                    for y, rows in screen.changed_bands(last, frame):
                        writer.write(ws.encode_frame(screen.encode_band(frame, y, rows), ws.OP_BINARY))
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

    async def wake(self):
        """Despierta la pantalla con Mayúsculas (no hace nada en las apps). El salvapantallas
        del lanzador a veces no enciende con la primera pulsación y sí con la segunda: se
        comprueba el brillo y se reintenta."""
        for _ in range(3):
            self.keyboard.set(keys.KEY_LEFTSHIFT, True)
            await asyncio.sleep(0.04)
            self.keyboard.set(keys.KEY_LEFTSHIFT, False)
            for _ in range(12):
                await asyncio.sleep(0.1)
                if device_status("", self.backlight)["brightness"] != 0:
                    return

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
                await self.wake()
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
    server = Server(args)
    hosts = args.listen or [tailscale_ip(timeout_s=600)]
    hosts = [h for h in hosts if h]
    if not hosts:
        log("no Tailscale IP and no --listen: nothing to listen on")
        sys.exit(1)
    srv = await asyncio.start_server(server.handle, hosts, args.port)
    log("listening on " + ", ".join(f"http://{h}:{args.port}/" for h in hosts))
    async with srv:
        await srv.serve_forever()


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
