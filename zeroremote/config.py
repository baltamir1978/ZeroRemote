# SPDX-License-Identifier: MIT
"""Los interruptores (los cambia la app «Remote» del Cardputer) y el estado que ve la app.

- Opciones: ~/.config/zeroremote/remote.conf, líneas clave=valor. La app lo reescribe con
  temporal + rename y el servicio mira su fecha cada 2 s.
    screen=on|off   la pantalla y el teclado remotos (por defecto on)
    files=on|off    compartir archivos (por defecto off: escribir en el aparato desde la red
                    tiene que pedirse)
- Estado: $XDG_RUNTIME_DIR/zeroremote/status (en RAM), clave=valor, para que la app enseñe
  la dirección y quién está conectado sin hablar con el servicio.
"""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    screen: bool = True
    files: bool = False

    @property
    def any(self) -> bool:
        return self.screen or self.files


def config_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "zeroremote", "remote.conf")


def status_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, "zeroremote", "status")


def parse(text: str) -> Settings:
    s = Settings()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if value not in ("on", "off"):
            continue
        if key == "screen":
            s.screen = value == "on"
        elif key == "files":
            s.files = value == "on"
    return s


def load(path: str) -> Settings:
    try:
        with open(path) as f:
            return parse(f.read())
    except OSError:
        return Settings()


def mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def write_status(path: str, values: dict):
    """Temporal + rename: la app nunca lee un fichero a medias."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")
    os.replace(tmp, path)


def settings_text(s: Settings) -> str:
    # El mismo texto que escribe la app (remote::settings_text en remote_settings.cpp).
    return ("# ZeroRemote: switches (changed from the Remote app)\n"
            f"screen={'on' if s.screen else 'off'}\n"
            f"files={'on' if s.files else 'off'}\n")


def save(path: str, s: Settings):
    """Temporal + rename, como la app: ni ella ni el servicio leen nunca un fichero a medias."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".web.tmp"
    with open(tmp, "w") as f:
        f.write(settings_text(s))
    os.replace(tmp, path)

