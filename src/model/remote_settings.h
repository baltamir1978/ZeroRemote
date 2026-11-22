/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <string>

namespace remote {

// Los dos interruptores, tal como los lee el servicio (zeroremote/config.py) de
// ~/.config/zeroremote/remote.conf. Los valores por defecto tienen que ser los mismos allí.
struct Settings {
    bool screen = true; // pantalla y teclado remotos
    bool files = false; // compartir archivos: escribir en el aparato desde la red se pide
};

Settings parse_settings(const std::string& text);
std::string settings_text(const Settings& settings);

// Lo que el servicio deja en $XDG_RUNTIME_DIR/zeroremote/status cada 2 s.
struct Status {
    bool known = false; // había fichero: el servicio está (o estuvo hace poco) en marcha
    bool listening = false;
    std::string url;
    int clients = 0;
    std::string last_client;
};

Status parse_status(const std::string& text);

// Una línea para la pantalla: quién mira, o por qué no hay nadie.
std::string status_line(const Status& status, const Settings& settings);

} // namespace remote
