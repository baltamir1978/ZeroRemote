/*
 * SPDX-License-Identifier: MIT
 */

#include "remote_settings.h"

#include <cstdlib>
#include <sstream>

namespace remote {
namespace {

std::string trim(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) {
        return "";
    }
    const auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

// Llama a `fn(clave, valor)` por cada línea «clave=valor» (sin comentarios ni basura).
template <typename Fn>
void for_each_pair(const std::string& text, Fn fn) {
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') {
            continue;
        }
        const auto eq = line.find('=');
        if (eq == std::string::npos || eq == 0) {
            continue;
        }
        fn(trim(line.substr(0, eq)), trim(line.substr(eq + 1)));
    }
}

} // namespace

Settings parse_settings(const std::string& text) {
    Settings s;
    for_each_pair(text, [&](const std::string& key, const std::string& value) {
        if (value != "on" && value != "off") {
            return;
        }
        if (key == "screen") {
            s.screen = value == "on";
        } else if (key == "files") {
            s.files = value == "on";
        }
    });
    return s;
}

std::string settings_text(const Settings& settings) {
    std::ostringstream out;
    out << "# ZeroRemote: switches (changed from the Remote app)\n";
    out << "screen=" << (settings.screen ? "on" : "off") << "\n";
    out << "files=" << (settings.files ? "on" : "off") << "\n";
    return out.str();
}

Status parse_status(const std::string& text) {
    Status s;
    for_each_pair(text, [&](const std::string& key, const std::string& value) {
        s.known = true;
        if (key == "listening") {
            s.listening = value == "1";
        } else if (key == "url") {
            s.url = value;
        } else if (key == "clients") {
            s.clients = std::atoi(value.c_str());
        } else if (key == "last_client") {
            s.last_client = value;
        }
    });
    return s;
}

std::string status_line(const Status& status, const Settings& settings) {
    if (!settings.screen && !settings.files) {
        return "Off: nothing is shared";
    }
    if (!status.known) {
        return "Service not running";
    }
    if (!status.listening) {
        return "Waiting for Tailscale...";
    }
    if (status.clients == 1) {
        return "Watching: " + status.last_client;
    }
    if (status.clients > 1) {
        return "Watching: " + std::to_string(status.clients) + " devices";
    }
    return settings.screen ? "Nobody watching" : "Ready";
}

} // namespace remote
