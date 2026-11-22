#!/bin/sh
# Instala (o actualiza) ZeroRemote en el Cardputer por SSH y lo deja arrancado.
#   Tools/instalar.sh            → en cpzero
#   Tools/instalar.sh <host>     → en otro
# Va a ~/.local/share/zeroremote del usuario y como servicio de usuario: sin root.
set -eu
HOST=${1:-cpzero}
cd "$(dirname "$0")/.."

python3 -m unittest -q tests/test_zeroremote.py

tar -c --exclude=__pycache__ zeroremote systemd/zeroremote.service | ssh "$HOST" '
  set -eu
  dest=$HOME/.local/share/zeroremote
  rm -rf "$dest.new" && mkdir -p "$dest.new" && tar -x -C "$dest.new"
  mkdir -p "$HOME/.config/systemd/user"
  mv "$dest.new/systemd/zeroremote.service" "$HOME/.config/systemd/user/"
  rmdir "$dest.new/systemd"
  rm -rf "$dest" && mv "$dest.new" "$dest"
  systemctl --user daemon-reload
  systemctl --user enable zeroremote.service >/dev/null 2>&1
  systemctl --user restart zeroremote.service
  sleep 2
  systemctl --user is-active zeroremote.service
  journalctl --user -u zeroremote -n 3 --no-pager -o cat
'
echo "Abre http://$HOST:8320/ desde un aparato de tu red de Tailscale."
