#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dibuja el icono de ZeroRemote: un Cardputer Zero visto de frente.

Dibujo propio (no una foto ni el logotipo de M5Stack), con lo que lo hace reconocible: cuerpo
gris, el Cap encima (franja lila y rosa), la pantalla en el centro con el lanzador, el
interruptor naranja a la derecha y cuatro filas de teclas negras con los modificadores de
colores. Fondo a sangre y el aparato dentro de la zona segura (80 % central), para que
Android pueda recortarlo en círculo o en cuadrado redondeado.

Genera zeroremote/web/icon.svg y, con ImageMagick, los PNG de 32, 180, 192 y 512 px.
"""

import os
import subprocess

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "zeroremote", "web")

BG = "#1b2026"
BODY = "#7d838a"
BODY_EDGE = "#5f656c"
KEYBED = "#2b3036"
KEY = "#101214"
SCREEN = "#05080b"
MODS = {  # (fila, columna): color, como en el teclado de verdad
    (1, 0): "#3d7bd9",  # sym
    (2, 0): "#e0559b",  # shift
    (3, 0): "#ef6a2c",  # fn
    (3, 1): "#e8cf3a",  # ctrl
    (3, 2): "#3cc3d6",  # alt
}


def svg() -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">',
        f'<rect width="512" height="512" fill="{BG}"/>',
        # Cap encima: GNSS (lila) y LoRa (rosa)
        '<rect x="118" y="112" width="138" height="30" rx="6" fill="#a597e6"/>',
        '<rect x="256" y="112" width="138" height="30" rx="6" fill="#e173b5"/>',
        # Cuerpo
        f'<rect x="58" y="132" width="396" height="274" rx="26" fill="{BODY_EDGE}"/>',
        f'<rect x="62" y="136" width="388" height="266" rx="22" fill="{BODY}"/>',
        # Pantalla con el lanzador: tres apps, la del centro seleccionada
        f'<rect x="146" y="150" width="220" height="104" rx="8" fill="{SCREEN}"/>',
        '<rect x="156" y="160" width="200" height="84" rx="4" fill="#0f2a33"/>',
        '<rect x="168" y="182" width="44" height="44" rx="10" fill="#2f7fd1"/>',
        # (con rellenos, no con stroke: el renderizador de ImageMagick no pinta contornos)
        '<rect x="230" y="174" width="60" height="60" rx="13" fill="#5ad1e6"/>',
        '<rect x="235" y="179" width="50" height="50" rx="10" fill="#1e3a44"/>',
        '<rect x="244" y="192" width="30" height="24" rx="4" fill="#5ad1e6"/>',
        '<rect x="248" y="196" width="22" height="16" rx="2" fill="#1e3a44"/>',
        '<rect x="274" y="199" width="5" height="10" rx="1" fill="#5ad1e6"/>',
        '<rect x="251" y="199" width="10" height="10" rx="1" fill="#5ad1e6"/>',
        '<rect x="300" y="182" width="44" height="44" rx="22" fill="#3d63e0"/>',
        # Panel izquierdo (logo, sin letras) y botón
        f'<rect x="76" y="156" width="56" height="44" rx="6" fill="{BODY_EDGE}"/>',
        '<circle cx="104" cy="230" r="11" fill="#1a1d20"/>',
        # Interruptor naranja a la derecha
        '<rect x="382" y="158" width="52" height="30" rx="7" fill="#ef5a2a"/>',
        '<rect x="408" y="164" width="20" height="18" rx="4" fill="#ffd9c9"/>',
        '<circle cx="408" cy="228" r="11" fill="#1a1d20"/>',
        # Teclado
        f'<rect x="72" y="268" width="368" height="124" rx="12" fill="{KEYBED}"/>',
    ]
    cols, kw, kh, gap = 10, 30, 22, 5.5
    x0 = 72 + (368 - (cols * kw + (cols - 1) * gap)) / 2
    for row in range(4):
        y = 278 + row * 28
        for col in range(cols):
            x = x0 + col * (kw + gap)
            parts.append(f'<rect x="{x:.1f}" y="{y}" width="{kw}" height="{kh}" rx="5" fill="{KEY}"/>')
            if (row, col) in MODS:
                parts.append(f'<rect x="{x + 5:.1f}" y="{y + 5}" width="{kw - 10}" height="7" rx="2" fill="{MODS[(row, col)]}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    path = os.path.join(OUT, "icon.svg")
    with open(path, "w") as f:
        f.write(svg())
    for size in (32, 180, 192, 512):
        subprocess.run(["magick", "-background", "none", "-density", "384", path,
                        "-resize", f"{size}x{size}", os.path.join(OUT, f"icon-{size}.png")], check=True)
    print("ok:", ", ".join(sorted(f for f in os.listdir(OUT) if f.startswith("icon"))))


if __name__ == "__main__":
    main()
