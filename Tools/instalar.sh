#!/bin/sh
# Compila el .deb (app Remote + servicio) y lo instala en el Cardputer por SSH.
#   Tools/instalar.sh            → en cpzero
#   Tools/instalar.sh <host>     → en otro
# Ojo: el lanzador 0.6.105 se cae con 20 apps (CardputerZero/launcher#268): antes de
# instalar en otro aparato, contar las entradas de /usr/share/APPLaunch/applications.
set -eu
HOST=${1:-cpzero}
cd "$(dirname "$0")/.."

python3 -m unittest -q tests/test_zeroremote.py
Tools/compilar.sh pruebas
Tools/compilar.sh deb
DEB=$(ls -t dist/ZeroRemote_*_arm64.deb | head -1)
scp -q "$DEB" "$HOST:/tmp/"
ssh "$HOST" "
  set -eu
  n=\$(ls /usr/share/APPLaunch/applications/*.desktop 2>/dev/null | grep -v zeroremote | wc -l)
  if [ \"\$n\" -ge 19 ] && [ ! -e /usr/share/APPLaunch/applications/zeroremote.desktop ]; then
    echo \"Hay \$n apps en el lanzador: con Remote serían 20 y el lanzador se cae (launcher#268).\" >&2
    exit 1
  fi
  sudo apt-get install -y -q /tmp/$(basename "$DEB") >/dev/null
  sleep 3
  systemctl is-active zeroremote.service
  journalctl -u zeroremote -n 3 --no-pager -o cat
"
echo "Abre la app Remote en el Cardputer y escanea el QR, o ve a http://$HOST:8320/."
