# SPDX-License-Identifier: MIT
"""Teclas: se escriben en el propio dispositivo del teclado del Cardputer.

Escribir un input_event en /dev/input/eventN lo inyecta en el núcleo como si viniera del
teclado (el usuario del aparato está en el grupo `input`): lo reciben el lanzador, las apps y
zeropowerd, que despierta la pantalla igual que con una tecla de verdad. No hace falta uinput
ni root.
"""

import fcntl
import os
import struct
import time

EV_SYN, EV_KEY = 0, 1
SYN_REPORT = 0
KEY_A, KEY_ENTER, KEY_ESC, KEY_LEFTSHIFT = 30, 28, 1, 42
KEY_MAX = 0x2FF
EVENT = struct.Struct("llHHi")  # timeval (el núcleo pone la hora), type, code, value


def _eviocgbit_key(size: int) -> int:
    # _IOC(_IOC_READ, 'E', 0x20 + EV_KEY, size)
    return (2 << 30) | (size << 16) | (ord("E") << 8) | (0x20 + EV_KEY)


def find_keyboard(root: str = "/dev/input") -> str:
    """El primer dispositivo con letras, Enter y Esc: el teclado, no el IR ni los botones."""
    size = KEY_MAX // 8 + 1
    for name in sorted(os.listdir(root)):
        if not name.startswith("event"):
            continue
        path = os.path.join(root, name)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            bits = bytearray(size)
            fcntl.ioctl(fd, _eviocgbit_key(size), bits)
        except OSError:
            continue
        finally:
            os.close(fd)
        if all(bits[k // 8] >> (k % 8) & 1 for k in (KEY_A, KEY_ENTER, KEY_ESC)):
            return path
    raise FileNotFoundError("no keyboard found in " + root)


class Keyboard:
    """Pulsa y suelta teclas. Recuerda las pulsadas para soltarlas si el navegador se va."""

    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_WRONLY)
        self.down = set()

    def _emit(self, code: int, value: int):
        os.write(self.fd, EVENT.pack(0, 0, EV_KEY, code, value) + EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0))

    def set(self, code: int, pressed: bool):
        if not 0 < code <= KEY_MAX:
            return
        if pressed:
            self.down.add(code)
        elif code in self.down:
            self.down.discard(code)
        else:
            return  # soltar una tecla que no está pulsada: nada
        self._emit(code, 1 if pressed else 0)

    def tap(self, code: int, hold_s: float = 0.04):
        self.set(code, True)
        time.sleep(hold_s)
        self.set(code, False)

    def release_all(self):
        for code in list(self.down):
            self.set(code, False)

    def close(self):
        self.release_all()
        os.close(self.fd)
