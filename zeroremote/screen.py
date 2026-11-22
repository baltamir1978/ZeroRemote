# SPDX-License-Identifier: MIT
"""La pantalla: leer el framebuffer y mandar sólo las filas que cambian.

La pantalla del Cardputer Zero es un panel SPI de 320×170 en RGB565 que el núcleo expone en
/dev/fb0. Leerla cuesta 0,1 ms; lo caro es comprimir y mandar por la wifi, así que entre dos
imágenes se buscan las franjas de filas que han cambiado y sólo esas se comprimen (en un
menú suele ser el reloj o la fila seleccionada: unos cientos de bytes).

Mensaje binario de una franja: tipo (1 byte, 1), fila inicial y número de filas (u16 LE),
y las filas en RGB565 comprimidas con zlib (el navegador las abre con DecompressionStream
«deflate»).
"""

import struct
import zlib

WIDTH, HEIGHT, BPP = 320, 170, 2
STRIDE = WIDTH * BPP
FRAME_BYTES = STRIDE * HEIGHT
MSG_BAND = 1


def read_frame(path: str = "/dev/fb0") -> bytes:
    with open(path, "rb", buffering=0) as f:
        data = f.read(FRAME_BYTES)
    if len(data) != FRAME_BYTES:
        raise OSError(f"short read from {path}: {len(data)} bytes")
    return data


def changed_bands(old, new: bytes, gap: int = 6):
    """Franjas (fila inicial, nº de filas) que difieren entre `old` y `new`.

    Dos cambios separados por menos de `gap` filas iguales van en la misma franja: cada
    mensaje tiene su cabecera y su arranque de zlib, y muchas franjas finas salen más caras
    que una algo más alta. Sin imagen anterior (`old` es None) va la pantalla entera.
    """
    if old is None:
        return [(0, HEIGHT)]
    bands = []
    start = last = None
    for y in range(HEIGHT):
        a = y * STRIDE
        if old[a:a + STRIDE] != new[a:a + STRIDE]:
            if start is None:
                start = y
            elif y - last > gap:
                bands.append((start, last - start + 1))
                start = y
            last = y
    if start is not None:
        bands.append((start, last - start + 1))
    return bands


def encode_band(frame: bytes, y: int, rows: int, level: int = 1) -> bytes:
    # Nivel 1: en el CM0 una foto a pantalla completa sale en 11 ms y 44 KB; el nivel 6 tarda
    # más del doble para ahorrar un 10 %.
    body = zlib.compress(frame[y * STRIDE:(y + rows) * STRIDE], level)
    return struct.pack("<BHH", MSG_BAND, y, rows) + body
