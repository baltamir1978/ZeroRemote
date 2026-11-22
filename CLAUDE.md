# ZeroRemote

La pantalla, el teclado y los archivos del **M5Stack Cardputer Zero** desde el navegador, por
Tailscale (`http://<IP de Tailscale>:8320/`), y la app **Remote** del lanzador que los enciende
y apaga y enseña la dirección en un QR. Qué hace y cómo se usa está en `README.md`; aquí va lo
que hace falta para tocarlo.

De `~/Proyectos/CLAUDE.md` valen el estilo (comentarios, documentación y commits en español
explicando el porqué; pocas dependencias; lógica pura con pruebas), que el repositorio es
**público** y la entrega (commit que empieza por la versión, push). La **web está en español**
(es para Bruno); la **app, en inglés**, como las demás del Cardputer (podría ir a la tienda).

## Qué hay en el repositorio

Dos partes que van en el mismo `.deb`:

- **El servicio** (`zeroremote/`, Python 3.13, **sólo biblioteca estándar**: en el Cardputer no
  se instala nada con pip). Se instala en `/usr/lib/zeroremote` y corre como servicio del
  sistema con `User=1000` (`packaging/zeroremote.service`), como zeropowerd: la tienda sólo
  admite unidades en `usr/lib/systemd/system` que no corran como root.
  - `ws.py` WebSocket mínimo; `screen.py` framebuffer y franjas de filas que cambian; `keys.py`
    escribir `input_event` en el teclado; `files.py` carpetas compartidas y comprobación de
    rutas; `config.py` interruptores y fichero de estado; `server.py` asyncio (HTTP, WebSocket,
    API de archivos, bucle que vigila los interruptores).
  - Página en `zeroremote/web/index.html`, sin dependencias: pantalla + botones arriba y
    archivos debajo, en la misma página (Bruno: «no hacen falta pestañas»).
- **La app Remote** (C++17 + LVGL 9.5, base de ZeroPower, que viene de la plantilla oficial):
  `src/`, `CMakeLists.txt`, `cmake/`, `assets/`. Es una sola pantalla (`HomeScreen`, en
  `src/view/screens/home_screen.*`): QR (`lv_qrcode`, activado en los dos `lv_conf_*.h`), dos
  interruptores y quién mira. La lógica pura en `src/model/remote_settings.*` con
  `tests/remote_model_test.cpp`.

## Cómo hablan la app y el servicio

- **Interruptores**: `~/.config/zeroremote/remote.conf` (`screen=on|off`, por defecto on;
  `files=on|off`, por defecto **off**). La app lo reescribe con temporal + rename; el servicio
  mira la fecha cada 2 s. Los valores por defecto están en `config.py` y en
  `remote_settings.h`: **tienen que coincidir**.
- **Estado**: el servicio escribe `$XDG_RUNTIME_DIR/zeroremote/status` (`listening`, `url`,
  `screen`, `files`, `clients`, `last_client`) cada 2 s; la app lo lee cada 0,5 s.
- **La web también cambia los interruptores** (`POST /api/settings?screen=on|off&files=on|off`,
  permitido aunque archivos esté apagado: es como se enciende). Escribe el mismo fichero y el
  mismo texto que la app (`config.settings_text` = `remote::settings_text`) y lo aplica ya. La
  app relee el fichero cada 0,5 s para no pisar un cambio de la web.
- Con los dos interruptores apagados el servicio cierra el puerto. Apagar la pantalla corta a
  quien mira; apagar archivos corta una subida a medias.

## Detalles que costó averiguar

- Protocolo de la pantalla: binario = franja (`<BHH` tipo 1, fila, nº de filas + zlib de
  RGB565); texto = JSON. Del navegador: `{"t":"key","code":n,"down":bool}`,
  `{"t":"tap","code":n}`, `{"t":"wake"}`. Del servidor: `{"t":"status",...}` cada 3 s y
  enseguida tras una tecla. Cada cliente lleva su «último cuadro enviado»: uno lento recibe
  menos imágenes, nunca rotas (`writer.drain()` es lo que frena).
- Archivos: raíces Music, Pictures, Videos, Downloads, Documents y Tracks (ZeroGPS) bajo
  `$HOME`; toda ruta pasa por `files.resolve` (realpath + `commonpath`, también enlaces). Subir
  escribe en `<nombre>.part` (oculto) y renombra; nunca pisa («nombre (1)»); deja 200 MB libres.
  API: `GET /api/info`, `GET /api/files`, `GET /api/download`, `POST /api/upload|mkdir|delete`
  con `root` y `path` en la query (subir: el cuerpo en crudo, no multipart).
- Teclas: códigos de `linux/input-event-codes.h`. **El teclado `tca8418c` no tiene
  `KEY_MINUS` (12) ni `KEY_EQUAL` (13)** y el núcleo descarta lo que el dispositivo no anuncia:
  «-», «+» y «*» van por las del teclado numérico (74, 78, 55).
- **Despertar y desbloquear** (tocar la pantalla en la web → `{"t":"wake","unlock":true}`):
  Mayúsculas hasta que hay brillo (el salvapantallas a veces no enciende a la primera) y, si
  `screen.is_lockscreen` ve el aviso amarillo «Press TAB/ENTER to unlock» (franja x 60-180,
  y 2-17: ≥ 40 px amarillos, ≤ 25 %, y ≥ 75 % amarillo o negro), TAB + ENTER, hasta 3 tandas.
  Ajustado con capturas reales (`tests/data/top_*.bin`, las 20 filas de arriba): bloqueo
  110-144 px amarillos, lanzador 0. Dentro de una app no se manda nada.
- **Tocar a los lados en el lanzador** (`{"t":"touch","x":0..1}`; la web manda dónde se tocó):
  apagada o bloqueada → como arriba; si `screen.is_launcher_home` (≥ 40 px amarillos del
  «ZERO» en x 4-46, y 3-17, **y** las dos flechas grises en x 3-16 / 303-317, y 77-98) y
  x < 0,25 o > 0,75 → flecha izquierda/derecha, en medio → ENTER; si no, nada. Hacen falta las flechas: IP Panel
  también tiene un título amarillo ahí («IP INFO»). Datos de prueba: `tests/data/mid_home.bin`
  (filas 76-99 del lanzador).
- **El lanzador (APPLaunch 0.6.105) se cae al arrancar con 20 apps**
  (`free(): invalid next size`; [launcher#268](https://github.com/CardputerZero/launcher/issues/268)).
  `Tools/instalar.sh` se niega si ya hay 19. Los **iconos del lanzador tienen que ser PNG de 8
  bits**: ImageMagick saca 16 desde el SVG (se convierte con `-depth 8 PNG32:`).
- Iconos: dibujo propio de un Cardputer Zero (no foto ni logo de M5Stack),
  `Tools/generar_icono.py` (ImageMagick **no pinta `stroke`**: los contornos van con rellenos).

## Compilar y probar

```sh
python3 -m unittest -v tests/test_zeroremote.py   # servicio (incluye la API con un servidor real)
Tools/compilar.sh pruebas                          # app en el simulador + ctest
Tools/compilar.sh deb                              # dist/ZeroRemote_<versión>_rev1_arm64.deb
Tools/instalar.sh                                  # todo lo anterior + instalar en cpzero
```

- `.cache` es un enlace a `../ZeroTVBGone/.cache` (LVGL y el *sysroot*).
- Versión en `CMakeLists.txt`, `app-builder.json` y `zeroremote/__init__.py`, a la vez.
- Simulador sin pantalla: `Xvfb :98`, `SDL_RENDER_DRIVER=software`, `XDG_CONFIG_HOME` y
  `XDG_RUNTIME_DIR` a una carpeta con un `zeroremote/status` de prueba; teclas con
  `xdotool key --window`, captura con `import -window root -crop 320x170+287+118`.
- La web sin móvil: `google-chrome --headless=new --window-size=412,1300
  --virtual-time-budget=5000 --screenshot=<png> http://cpzero:8320/`.
- En el aparato: `systemctl status zeroremote`, `journalctl -u zeroremote`.

## Estado

- **0.4.0 (22-nov-2026) — modo claro/oscuro; preparada para publicar.** Botón ☀/☾ junto al
  título (sin elegir, el del sistema; la elección en `localStorage`, aplicada antes de pintar).
  Entre 0.3.3 y 0.3.6: vuelve «tirar para recargar», ↑ encima de ↓, fila «Carpeta superior» y
  espacio bajo listas de menos de 5 filas. **Para la tienda falta**: grabar un vídeo en el
  aparato (la primera publicación lo pide, sin metadatos de ubicación) y decidir cuándo, por
  [launcher#268](https://github.com/CardputerZero/launcher/issues/268) (con 19 apps
  instaladas, Remote tumbaría el lanzador). `app-builder.json` está al día; no se ha enviado.
- **0.3.2 (22-nov-2026) — contador de FPS.** Lo pidió Bruno. Cuenta imágenes completas
  pintadas (marca de fin de imagen), no franjas: medido, 140 franjas eran 77 imágenes. 20 fps
  en el desbloqueo (el tope, `--fps`), 5-11 pasando apps en el lanzador; 0 con la pantalla
  quieta.
- **0.3.1 (22-nov-2026) — la página ya no se mueve.** Bruno notó que se desplazaba unos
  milímetros arriba y abajo (y un toque podía caer donde no era). Dos causas: los textos de
  estado de la cabecera cambiaban de una a dos líneas según su largo, y sobre la pantalla
  `touch-action: manipulation` dejaba que un toque con el dedo algo movido desplazara la
  página. Ahora la cabecera tiene dos filas de alto fijo (medido en Chrome a 360 y 412 px: 54 px
  y la pantalla a la misma altura con cualquier texto) y la pantalla tiene `touch-action: none`.
  (En 0.3.3 se quitó `overscroll-behavior: none`: también anulaba el «tirar para recargar».) Regla: **nada por encima de la pantalla puede
  cambiar de alto con datos que se actualizan.**
- **0.3.0 (22-nov-2026) — interruptores en la web y ENTER en el centro.** Lo pidió Bruno.
  Probado en el aparato: desde la pantalla apagada, toques hasta Remote y abrirla sólo con
  toques; apagar y encender «File sharing» desde la web se ve en la app en ~1,5 s.
- **0.2.2 (22-nov-2026) — tocar a los lados pasa de app en el lanzador.** Lo pidió Bruno.
  Probado en el aparato: derecha, derecha, izquierda mueven el carrusel; el centro con el
  lanzador no hace nada; dentro de IP Panel los toques laterales no mandan nada.
- **0.2.1 (22-nov-2026) — tocar la pantalla desbloquea.** Lo pidió Bruno: que el primer toque
  mande TAB y ENTER y deje el lanzador. Probado en el aparato: dos veces de apagado y bloqueado
  al lanzador con un toque, y con el lanzador a la vista no manda nada. Instalada en cpzero.
- **0.2.0 (22-nov-2026) — archivos y app Remote; instalada en cpzero.** Compartir archivos
  (probado desde el portátil: 2,4 MB/s subida, 2,3 bajada, 20 MB idénticos) y la app con QR e
  interruptores (probada en el aparato: se abre desde el lanzador, apagar «File sharing» da 403
  en la web a los 2-3 s y encenderlo lo devuelve). Para hacer sitio en el lanzador Bruno quitó
  FactoryTest, GPS (el de origen), IR Chat y Keyboard Guide (desinstalados) y ocultó la
  calculadora (`app_Math: 0` en `~/.config/cardputerzero/config.json`; copia en
  `config.json.antes-20261122`). **Sin probar en el móvil**: escanear el QR, subir desde el
  móvil. No enviada a la tienda.
- **0.1.0 (22-nov-2026)** — pantalla y teclado. En el Pixel de Bruno el nombre `cpzero` no
  resuelve: hay que usar la IP (por eso el QR).
- Idea para después: versión por cable con adb (app de Android que llega al mismo servicio con
  `adb forward`); el adb del Cardputer es sólo USB y no tiene ningún aparato emparejado.
