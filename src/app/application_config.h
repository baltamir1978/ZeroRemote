/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <string>

namespace app {

// De momento sólo se recuerda el tema. Cada herramienta guardará lo suyo (tarjetas,
// señales) en ficheros aparte, no aquí.
struct ApplicationConfig {
    bool dark_mode = true;
};

bool load_application_config(const std::string& path,
                             ApplicationConfig& config,
                             std::string& error);
bool save_application_config(const std::string& path,
                             const ApplicationConfig& config,
                             std::string& error);

} // namespace app
