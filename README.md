# ZeroRemote

La pantalla del **M5Stack Cardputer Zero** en el navegador, en directo, y su teclado: para
manejarlo desde el móvil o el portátil sin tocarlo. Funciona a través de
[Tailscale](https://tailscale.com): sólo lo ven los aparatos de tu red de Tailscale.

```
http://cpzero:8320/
```

Si el nombre no resuelve en el móvil (pasa con el «DNS privado» de Android, que se salta el
de Tailscale), con la IP de Tailscale del aparato (la da `tailscale ip -4`):
`http://100.x.y.z:8320/`, escrito con `http://` delante. Se puede añadir a la pantalla de inicio desde el menú del navegador.

<p align="center"><img src="docs/captura.png" alt="ZeroRemote en un móvil: la pantalla del Cardputer con el lanzador y los botones de teclas" width="320"></p>

## Qué hace

- **Pantalla en directo** (320×170, ampliada y nítida). Sólo se mandan las filas que cambian:
  en un menú, unos cientos de bytes por cambio; con una foto a pantalla completa, unos 44 KB.
  Hasta 20 actualizaciones por segundo.
- **Teclado**: botones para Esc, Tab, Enter, flechas, borrar y espacio (mantenerlos pulsados
  mantiene la tecla: un Esc largo sale de las apps), el teclado del móvil para escribir, y
  cualquier teclado físico tecla a tecla.
- **Batería y consumo** en la cabecera.
- **Pantalla apagada**: tocarla la despierta (con Mayúsculas, que no hace nada en las apps).

## Cómo funciona

Un servicio en Python (sólo la biblioteca estándar) en el propio Cardputer:

- Lee la pantalla de `/dev/fb0` (RGB565) unas 20 veces por segundo **sólo mientras hay
  alguien mirando**; sin nadie conectado, duerme.
- Manda las franjas de filas que cambian, comprimidas con zlib, por un WebSocket. El navegador
  las descomprime (`DecompressionStream`) y las pinta en un `<canvas>`.
- Las teclas se escriben en el propio dispositivo del teclado (`/dev/input/event3`): el
  lanzador, las apps y ZeroPower las reciben como si fueran de verdad. Sin root ni `uinput`.
- Escucha **sólo en la IP de Tailscale** del aparato y rechaza clientes de fuera de
  `100.64.0.0/10`. En una wifi ajena (o en el punto de acceso del móvil) nadie más lo ve.

Medidas en el Cardputer: leer la pantalla 0,1 ms; comprimir una foto entera 11 ms.

## Instalar

Desde un ordenador con SSH al Cardputer:

```sh
Tools/instalar.sh          # en cpzero; o Tools/instalar.sh <host>
```

Lo copia a `~/.local/share/zeroremote` y lo deja como servicio de usuario
(`systemctl --user status zeroremote`). Hace falta que el usuario esté en los grupos `video` e
`input` (el del Cardputer ya lo está) y que el usuario tenga *linger* (sigue funcionando sin
sesión abierta).

Opciones (`python3 -m zeroremote --help`): `--port`, `--fps`, `--listen <ip>` (por defecto la
de Tailscale), `--any-client` (sólo para pruebas).

## Pruebas

```sh
python3 -m unittest -v tests/test_zeroremote.py
```

## Licencia

MIT.
