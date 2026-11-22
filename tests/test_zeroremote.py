# SPDX-License-Identifier: MIT
"""Pruebas de lo que no necesita el aparato: WebSocket, franjas de pantalla, teclas, estado."""

import asyncio
import os
import struct
import tempfile
import unittest
import zlib
from types import SimpleNamespace

from zeroremote import keys, screen, server, ws


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


if __name__ == "__main__":
    unittest.main()
