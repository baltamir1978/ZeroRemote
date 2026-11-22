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
# Tras las franjas de cada imagen nueva, un mensaje de un byte: la web cuenta las imágenes
# completas (los FPS de verdad: una imagen puede llegar en varias franjas).
MSG_FRAME_END = 2
FRAME_END = bytes([MSG_FRAME_END])


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


# --- Pantalla de bloqueo del lanzador ---
#
# El salvapantallas del lanzador, al despertar, pinta arriba a la izquierda «Press TAB to
# unlock» (o «Press ENTER to unlock») en amarillo. El lanzador también tiene «ZERO» en
# amarillo en ese sitio, pero no pasa de x≈45; el aviso llega hasta x≈190. Se cuentan los
# píxeles amarillos de la franja que sólo pisa el aviso.
LOCK_HINT_BOX = (60, 2, 180, 17)  # x0, y0, x1, y1 (sin incluir x1, y1)
LOCK_HINT_MIN_PIXELS = 40
# Y el resto de la franja, negro (la barra del aviso): una foto con algo amarillo arriba no
# cumple las dos cosas. Medido en el aparato: 84-87 % amarillo o negro (lo demás, el
# suavizado de las letras).
LOCK_HINT_MIN_PLAIN = 0.75
# Las letras son finas (medido: 6-8 % de la franja); mucho más amarillo es otra cosa.
LOCK_HINT_MAX_YELLOW = 0.25


def _is_yellow(p: int) -> bool:
    r = (p >> 11) & 31
    g = (p >> 5) & 63
    b = p & 31
    return r >= 22 and g >= 36 and b <= 12  # en 8 bits: R ≥ 180, G ≥ 145, B ≤ 100


def _is_dark(p: int) -> bool:
    return ((p >> 11) & 31) <= 6 and ((p >> 5) & 63) <= 12 and (p & 31) <= 6


def lock_hint_counts(frame: bytes):
    """(amarillos, negros, total) en la franja del aviso."""
    x0, y0, x1, y1 = LOCK_HINT_BOX
    yellow = dark = 0
    for y in range(y0, y1):
        row = frame[y * STRIDE + x0 * BPP:y * STRIDE + x1 * BPP]
        for i in range(0, len(row), 2):
            p = row[i] | (row[i + 1] << 8)
            if _is_yellow(p):
                yellow += 1
            elif _is_dark(p):
                dark += 1
    return yellow, dark, (x1 - x0) * (y1 - y0)


def is_lockscreen(frame: bytes) -> bool:
    """¿Está a la vista la pantalla de bloqueo del lanzador (con su aviso)?"""
    yellow, dark, total = lock_hint_counts(frame)
    return (LOCK_HINT_MIN_PIXELS <= yellow <= LOCK_HINT_MAX_YELLOW * total
            and (yellow + dark) >= LOCK_HINT_MIN_PLAIN * total)


# --- La pantalla de inicio del lanzador ---
#
# Se reconoce por el «ZERO» amarillo de arriba a la izquierda y las dos flechas grises
# («‹ ›») a los lados del carrusel. Medido en el aparato: «ZERO» 86 px amarillos en x 6-43,
# y 5-14; flechas en x 6-12 y 306-313, y 80-94, gris ~(130,130,130) con su suavizado.
HOME_TITLE_BOX = (4, 3, 46, 17)
HOME_ARROW_BOXES = ((3, 77, 16, 98), (303, 77, 317, 98))
HOME_TITLE_MIN = 40
HOME_ARROW_MIN = 15


def _rgb(p: int):
    return ((p >> 11) & 31) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31


def _count(frame: bytes, box, test) -> int:
    x0, y0, x1, y1 = box
    n = 0
    for y in range(y0, y1):
        row = frame[y * STRIDE + x0 * BPP:y * STRIDE + x1 * BPP]
        for i in range(0, len(row), 2):
            if test(row[i] | (row[i + 1] << 8)):
                n += 1
    return n


def _is_arrow_grey(p: int) -> bool:
    r, g, b = _rgb(p)
    return 90 <= r <= 225 and abs(r - g) <= 25 and abs(g - b) <= 25


def is_launcher_home(frame: bytes) -> bool:
    """¿Se ve el carrusel de apps del lanzador? (no el bloqueo, no una app)."""
    if _count(frame, HOME_TITLE_BOX, _is_yellow) < HOME_TITLE_MIN:
        return False
    return all(_count(frame, box, _is_arrow_grey) >= HOME_ARROW_MIN for box in HOME_ARROW_BOXES)

