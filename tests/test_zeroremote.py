# SPDX-License-Identifier: MIT
"""Pruebas de lo que no necesita el aparato: WebSocket, franjas de pantalla, teclas, estado."""

import asyncio
import json
import os
import struct
import tempfile
import unittest
import zlib
from types import SimpleNamespace

import threading
import urllib.error
import urllib.parse
import urllib.request

from zeroremote import config, files, keys, screen, server, ws


class WebSocketTest(unittest.TestCase):
    def test_accept_key_rfc_example(self):
        # El ejemplo de la RFC 6455, sección 1.3.
        self.assertEqual(ws.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_encode_lengths(self):
        self.assertEqual(ws.encode_frame(b"hi", ws.OP_TEXT), b"\x81\x02hi")
        mid = ws.encode_frame(b"x" * 300, ws.OP_BINARY)
        self.assertEqual(mid[:4], b"\x82\x7e\x01\x2c")
        big = ws.encode_frame(b"x" * 70000, ws.OP_BINARY)
        self.assertEqual(big[1], 127)
        self.assertEqual(struct.unpack(">Q", big[2:10])[0], 70000)

    def _masked(self, payload, opcode=ws.OP_TEXT, mask=b"\x11\x22\x33\x44"):
        n = len(payload)
        head = bytes([0x80 | opcode])
        head += bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return head + mask + body

    def _read(self, data):
        async def go():
            r = asyncio.StreamReader()
            r.feed_data(data)
            r.feed_eof()
            return await ws.read_frame(r)
        return asyncio.run(go())

    def test_read_masked_frames(self):
        self.assertEqual(self._read(self._masked(b'{"t":"tap","code":1}')), (ws.OP_TEXT, b'{"t":"tap","code":1}'))
        self.assertEqual(self._read(self._masked(b"a" * 1000)), (ws.OP_TEXT, b"a" * 1000))
        self.assertEqual(self._read(self._masked(b"", ws.OP_CLOSE)), (ws.OP_CLOSE, b""))

    def test_rejects_unmasked_and_fragmented(self):
        with self.assertRaises(ws.ProtocolError):
            self._read(b"\x81\x02hi")  # sin máscara
        with self.assertRaises(ws.ProtocolError):
            self._read(b"\x01\x82" + b"\0\0\0\0hi")  # sin FIN

    def test_unmask_matches_bytewise(self):
        data = bytes(range(256)) * 3 + b"xyz"
        mask = b"\xde\xad\xbe\xef"
        self.assertEqual(ws.unmask(data, mask), bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def frame_with(rows_changed=(), base=b"\x00"):
    data = bytearray(base * screen.FRAME_BYTES)
    for y in rows_changed:
        data[y * screen.STRIDE] = 0xFF
    return bytes(data)


class ScreenTest(unittest.TestCase):
    def test_first_frame_is_whole_screen(self):
        self.assertEqual(screen.changed_bands(None, frame_with()), [(0, screen.HEIGHT)])

    def test_no_change(self):
        f = frame_with()
        self.assertEqual(screen.changed_bands(f, f), [])

    def test_bands_merge_close_rows(self):
        old = frame_with()
        # 3 y 7 están a 4 filas: una franja; 100 va aparte; la última fila también cuenta.
        new = frame_with([3, 7, 100, screen.HEIGHT - 1])
        self.assertEqual(screen.changed_bands(old, new), [(3, 5), (100, 1), (screen.HEIGHT - 1, 1)])

    def test_encode_band_roundtrip(self):
        f = bytes((i * 7) & 0xFF for i in range(screen.FRAME_BYTES))
        msg = screen.encode_band(f, 10, 3)
        kind, y, rows = struct.unpack("<BHH", msg[:5])
        self.assertEqual((kind, y, rows), (screen.MSG_BAND, 10, 3))
        self.assertEqual(zlib.decompress(msg[5:]), f[10 * screen.STRIDE:13 * screen.STRIDE])


class KeyboardTest(unittest.TestCase):
    def test_press_release_and_release_all(self):
        with tempfile.NamedTemporaryFile() as tmp:
            kb = keys.Keyboard(tmp.name)
            kb.set(30, True)
            kb.set(30, True)   # repetida: se manda (el núcleo la trata como repetición)
            kb.set(31, False)  # no estaba pulsada: nada
            kb.set(0, True)    # código no válido: nada
            kb.set(1, True)
            kb.close()         # suelta las dos que siguen pulsadas (A y Esc)
            data = open(tmp.name, "rb").read()
        events = [keys.EVENT.unpack_from(data, i)[2:] for i in range(0, len(data), keys.EVENT.size)]
        key_events = [e for e in events if e[0] == keys.EV_KEY]
        self.assertEqual(key_events[:3], [(1, 30, 1), (1, 30, 1), (1, 1, 1)])
        self.assertEqual(sorted(key_events[3:]), [(1, 1, 0), (1, 30, 0)])
        # Cada tecla va seguida de su SYN_REPORT.
        self.assertEqual(len(events), 2 * len(key_events))


class StatusTest(unittest.TestCase):
    def test_device_status_from_sysfs(self):
        with tempfile.TemporaryDirectory() as root:
            bat = os.path.join(root, "bq27220-0")
            os.makedirs(bat)
            for name, value in {"type": "Battery", "capacity": "57", "status": "Discharging",
                                "current_now": "-231000"}.items():
                with open(os.path.join(bat, name), "w") as f:
                    f.write(value + "\n")
            bl = os.path.join(root, "backlight")
            os.makedirs(bl)
            with open(os.path.join(bl, "brightness"), "w") as f:
                f.write("100\n")
            self.assertEqual(server.find_battery(root), bat)
            s = server.device_status(bat, bl)
        self.assertEqual(s, {"t": "status", "battery": 57, "charging": False, "draw_ma": 231, "brightness": 100})

    def test_status_without_battery(self):
        s = server.device_status("", "")
        self.assertIsNone(s["battery"])
        self.assertIsNone(s["brightness"])

    def test_only_tailnet_and_loopback_clients(self):
        srv = server.Server.__new__(server.Server)
        srv.args = SimpleNamespace(any_client=False)
        self.assertTrue(srv.allowed(("100.101.102.103", 5000)))
        self.assertTrue(srv.allowed(("127.0.0.1", 5000)))
        self.assertFalse(srv.allowed(("192.168.1.20", 5000)))
        self.assertFalse(srv.allowed(("8.8.8.8", 5000)))
        self.assertFalse(srv.allowed(None))


class StaticTest(unittest.TestCase):
    def test_every_static_file_exists(self):
        for name, _ in server.STATIC.values():
            self.assertTrue(os.path.isfile(os.path.join(server.WEB_DIR, name)), name)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "Music")
        os.makedirs(os.path.join(self.root, "Album"))
        open(os.path.join(self.root, "a.mp3"), "w").close()
        open(os.path.join(self.root, ".oculto"), "w").close()
        open(os.path.join(self.root, "subiendo.mp3.part"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_stays_inside(self):
        self.assertEqual(files.resolve(self.root, "Album"), os.path.join(os.path.realpath(self.root), "Album"))
        self.assertEqual(files.resolve(self.root, "/Album"), os.path.join(os.path.realpath(self.root), "Album"))
        for bad in ("..", "../..", "Album/../../x", "../Music2"):
            with self.assertRaises(files.FileError):
                files.resolve(self.root, bad)

    def test_symlink_out_is_refused(self):
        os.symlink("/etc", os.path.join(self.root, "fuera"))
        with self.assertRaises(files.FileError):
            files.resolve(self.root, "fuera/passwd")

    def test_names(self):
        self.assertEqual(files.check_name(" canción.mp3 "), "canción.mp3")
        for bad in ("", ".", "..", "a/b", "x\0y", "n" * 300):
            with self.assertRaises(files.FileError):
                files.check_name(bad)

    def test_list_hides_dotfiles_and_parts_dirs_first(self):
        names = [(e["name"], e["dir"]) for e in files.list_dir(self.root)]
        self.assertEqual(names, [("Album", True), ("a.mp3", False)])

    def test_unique_path_never_overwrites(self):
        self.assertEqual(os.path.basename(files.unique_path(self.root, "b.mp3")), "b.mp3")
        self.assertEqual(os.path.basename(files.unique_path(self.root, "a.mp3")), "a (1).mp3")
        open(os.path.join(self.root, "a (1).mp3"), "w").close()
        self.assertEqual(os.path.basename(files.unique_path(self.root, "a.mp3")), "a (2).mp3")

    def test_delete_refuses_root(self):
        with self.assertRaises(files.FileError):
            files.delete(self.root, self.root)
        files.delete(os.path.join(self.root, "Album"), self.root)
        self.assertFalse(os.path.exists(os.path.join(self.root, "Album")))

    def test_space(self):
        with self.assertRaises(files.FileError):
            files.check_space(self.root, 10 ** 15)
        files.check_space(self.root, 10)


class ConfigTest(unittest.TestCase):
    def test_defaults_and_parse(self):
        self.assertEqual(config.parse(""), config.Settings(screen=True, files=False))
        s = config.parse("# x\nscreen = off\nfiles=on\nfiles=maybe\nbasura\n")
        self.assertEqual(s, config.Settings(screen=False, files=True))
        self.assertTrue(s.any)
        self.assertFalse(config.Settings(screen=False, files=False).any)

    def test_status_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "zeroremote", "status")
            config.write_status(path, {"listening": 1, "url": "http://x:8320/"})
            self.assertEqual(open(path).read(), "listening=1\nurl=http://x:8320/\n")


class FileApiTest(unittest.TestCase):
    """El servidor de verdad, en 127.0.0.1, con un HOME de mentira."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        args = SimpleNamespace(fb="/nonexistent", fps=1, keyboard="/nonexistent", any_client=False)
        self.srv = server.Server(args)
        self.srv.home = self.home
        self.srv.settings = config.Settings(screen=True, files=True)
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            self.listener = self.loop.run_until_complete(asyncio.start_server(self.srv.handle, "127.0.0.1", 0))
            self.port = self.listener.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(5)

    def tearDown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.tmp.cleanup()

    def call(self, method, endpoint, body=None, **params):
        url = f"http://127.0.0.1:{self.port}{endpoint}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_upload_list_download_mkdir_delete(self):
        data = os.urandom(200_000)
        code, body, _ = self.call("POST", "/api/upload", data, root="music", path="", name="canción.mp3")
        self.assertEqual((code, json.loads(body)["name"]), (200, "canción.mp3"))
        code, body, _ = self.call("POST", "/api/upload", b"x", root="music", path="", name="canción.mp3")
        self.assertEqual(json.loads(body)["name"], "canción (1).mp3")  # no pisa

        code, body, _ = self.call("GET", "/api/files", root="music", path="")
        listing = json.loads(body)
        self.assertEqual([e["name"] for e in listing["entries"]], ["canción (1).mp3", "canción.mp3"])
        self.assertGreater(listing["free"], 0)

        code, body, headers = self.call("GET", "/api/download", root="music", path="canción.mp3")
        self.assertEqual((code, body), (200, data))
        self.assertIn("attachment", headers["Content-Disposition"])

        self.assertEqual(self.call("POST", "/api/mkdir", root="music", path="", name="Disco")[0], 200)
        self.assertEqual(self.call("POST", "/api/upload", b"y", root="music", path="Disco", name="t.mp3")[0], 200)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "Music", "Disco", "t.mp3")))
        self.assertEqual(self.call("POST", "/api/delete", root="music", path="Disco")[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.home, "Music", "Disco")))

    def test_refusals(self):
        open(os.path.join(self.home, "secreto"), "w").close()
        self.assertEqual(self.call("GET", "/api/download", root="music", path="../secreto")[0], 403)
        self.assertEqual(self.call("GET", "/api/files", root="etc", path="")[0], 404)
        self.assertEqual(self.call("POST", "/api/upload", b"x", root="music", path="", name="../x")[0], 400)
        self.assertEqual(self.call("POST", "/api/delete", root="music", path="")[0], 403)
        self.srv.settings = config.Settings(screen=True, files=False)
        code, body, _ = self.call("GET", "/api/files", root="music", path="")
        self.assertEqual(code, 403)
        info = json.loads(self.call("GET", "/api/info")[1])
        self.assertEqual((info["screen"], info["files"]), (True, False))


if __name__ == "__main__":
    unittest.main()
