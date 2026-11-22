# ZeroRemote

La pantalla y el teclado del **M5Stack Cardputer Zero** desde el navegador, por Tailscale
(`http://cpzero:8320/`). Qué hace y cómo se usa está en `README.md`; aquí va lo que hace falta
para tocarlo.

No es una app de Android ni de la tienda: de `~/Proyectos/CLAUDE.md` valen el estilo
(comentarios, documentación y commits en español explicando el porqué; pocas dependencias;
lógica pura con pruebas) y que el repositorio sería **público**. La página está en español
(es para Bruno, no va a la tienda).

## Cómo está hecho

- `zeroremote/` (Python 3.13, **sólo biblioteca estándar**: en el Cardputer no se instala nada
  con pip): `ws.py` (WebSocket mínimo), `screen.py` (framebuffer y franjas de filas que
  cambian), `keys.py` (escribir `input_event` en el teclado), `server.py` (asyncio: HTTP,
  WebSocket, estado del aparato, `wake`). Página en `zeroremote/web/index.html`, sin
  dependencias.
- Protocolo: binario = franja (`<BHH` tipo 1, fila, nº de filas + zlib de RGB565); texto =
  JSON. Del navegador: `{"t":"key","code":n,"down":bool}`, `{"t":"tap","code":n}`,
  `{"t":"wake"}`. Del servidor: `{"t":"status",battery,charging,draw_ma,brightness}` cada 3 s
  y enseguida tras una tecla.
- Cada cliente lleva su «último cuadro enviado»: uno lento recibe menos imágenes, nunca rotas.
  `writer.drain()` es lo que frena.
- Teclas: códigos de `linux/input-event-codes.h`. **El teclado `tca8418c` no tiene
  `KEY_MINUS` (12) ni `KEY_EQUAL` (13)** y el núcleo descarta lo que el dispositivo no anuncia:
  «-», «+» y «*» van por las del teclado numérico (74, 78, 55). Los 111 códigos que tiene se
  leen con `EVIOCGBIT`.
- **Despertar**: el salvapantallas del lanzador a veces no enciende con la primera pulsación
  (22-nov-2026, sin causa clara); `wake` manda Mayúsculas y reintenta hasta 3 veces mirando el
  brillo. Probado: 3 de 3, en ~0,1 s.
- Escucha sólo en la IP de `tailscale ip -4` (espera hasta 10 min a que Tailscale arranque) y
  rechaza clientes fuera de `100.64.0.0/10` salvo `--any-client`.

## Probar

```sh
python3 -m unittest -v tests/test_zeroremote.py
Tools/instalar.sh                     # pasa las pruebas, copia a cpzero y reinicia el servicio
```

- En el aparato: `systemctl --user status zeroremote`, `journalctl --user -u zeroremote`.
- Sin móvil: `google-chrome --headless=new --window-size=412,800 --virtual-time-budget=4000
  --screenshot=<png> http://cpzero:8320/` enseña la página como en un móvil.

## Estado

- **0.1.0 (22-nov-2026) — primera versión, instalada en cpzero.** Probado desde el portátil:
  página, WebSocket, imagen reconstruida idéntica al framebuffer (170 de 170 filas), teclas,
  `wake`, y la página en Chrome a tamaño de móvil. **Sin probar en el móvil de Bruno** (el
  teclado del móvil por `beforeinput`, mantener botones pulsados).
- Idea para después: versión por cable con adb (app de Android que llega al mismo servicio con
  `adb forward`); el adb del Cardputer es sólo USB y no tiene ningún aparato emparejado.
