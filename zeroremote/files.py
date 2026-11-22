# SPDX-License-Identifier: MIT
"""Compartir archivos: qué carpetas se ven y cómo se comprueba que nada se sale de ellas.

Sólo las carpetas de las apps y las normales del usuario, nunca el sistema entero: lo que se
comparte es para meter música, fotos o tracks, no para administrar el aparato. Cada ruta que
llega del navegador se resuelve (también los enlaces simbólicos) y tiene que quedar dentro de
su carpeta raíz.
"""

import os
import shutil
import stat

# (clave, lo que se ve, carpeta bajo $HOME)
ROOTS = [
    ("music", "Música", "Music"),
    ("pictures", "Imágenes", "Pictures"),
    ("videos", "Vídeos", "Videos"),
    ("downloads", "Descargas", "Downloads"),
    ("documents", "Documentos", "Documents"),
    ("tracks", "Tracks GPS", "Tracks"),
]

# Se deja libre al menos esto al subir: la tarjeta llena tumba el sistema (journal, apt...).
FREE_MARGIN = 200 * 1024 * 1024


class FileError(Exception):
    """Error que se le puede enseñar al usuario tal cual (con su código HTTP)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def roots(home: str):
    return [{"key": k, "label": label, "path": os.path.join(home, sub)} for k, label, sub in ROOTS]


def root_path(home: str, key: str) -> str:
    for k, _, sub in ROOTS:
        if k == key:
            return os.path.join(home, sub)
    raise FileError(404, "Carpeta desconocida")


def check_name(name: str) -> str:
    """Un nombre de archivo o carpeta, sin rutas: nada de «/», «..» ni caracteres nulos."""
    name = (name or "").strip()
    if not name or name in (".", "..") or "/" in name or "\0" in name or len(name.encode()) > 255:
        raise FileError(400, "Nombre no válido")
    return name


def resolve(root: str, rel: str) -> str:
    """La ruta absoluta de `rel` dentro de `root`; error si se sale (con «..» o un enlace)."""
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, (rel or "").lstrip("/")))
    if os.path.commonpath([base, target]) != base:
        raise FileError(403, "Fuera de la carpeta compartida")
    return target


def list_dir(path: str):
    """Carpetas primero y luego archivos, por nombre sin distinguir mayúsculas. Los ocultos
    (empiezan por «.») y los .part de subidas a medias no se enseñan."""
    try:
        names = os.listdir(path)
    except FileNotFoundError:
        raise FileError(404, "No existe")
    except NotADirectoryError:
        raise FileError(400, "No es una carpeta")
    entries = []
    for name in names:
        if name.startswith(".") or name.endswith(".part"):
            continue
        try:
            st = os.stat(os.path.join(path, name))
        except OSError:
            continue  # enlace roto, o desaparecido entre medias
        is_dir = stat.S_ISDIR(st.st_mode)
        entries.append({"name": name, "dir": is_dir, "size": 0 if is_dir else st.st_size, "mtime": int(st.st_mtime)})
    entries.sort(key=lambda e: (not e["dir"], e["name"].casefold()))
    return entries


def unique_path(folder: str, name: str) -> str:
    """`folder/name`, o «nombre (1).ext», «nombre (2).ext»... si ya existe: subir nunca pisa."""
    candidate = os.path.join(folder, name)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = os.path.join(folder, f"{stem} ({n}){ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def check_space(folder: str, incoming: int):
    free = shutil.disk_usage(folder).free
    if incoming > free - FREE_MARGIN:
        raise FileError(507, "No cabe: queda poco espacio en la tarjeta")


def delete(path: str, root: str):
    if os.path.realpath(path) == os.path.realpath(root):
        raise FileError(403, "La carpeta compartida no se borra")
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)
    else:
        raise FileError(404, "No existe")


def parse_range(header: str, size: int):
    """(inicio, fin incluido) de una cabecera «Range: bytes=…» de un solo tramo, o None si no
    hay o no se entiende (entonces va el archivo entero). Error 416 si se sale del archivo.
    Los reproductores de audio y vídeo del navegador piden tramos para poder adelantar."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if first == "":  # «bytes=-500»: los últimos 500
            n = int(last)
            if n <= 0:
                raise FileError(416, "Tramo no válido")
            return max(size - n, 0), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or start < 0 or end < start:
        raise FileError(416, "Tramo no válido")
    return start, min(end, size - 1)

