/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <string>

namespace platform {

// Una lectura del medidor de la batería (bq27220 en el Cardputer Zero), por sysfs.
struct BatteryReading {
    bool present = false;
    std::string status;   // "Charging", "Discharging", "Full", "Not charging"…
    int capacity = -1;    // %
    double voltage_v = 0.0;
    double current_ma = 0.0; // positivo = sale de la batería (consumo)
    double charge_mah = -1.0;
    double charge_full_mah = -1.0;

    bool discharging() const {
        return status == "Discharging";
    }
};

// La primera fuente de tipo «Battery» de /sys/class/power_supply ("" si no hay).
std::string find_battery_dir();
BatteryReading read_battery(const std::string& dir);

// Brillo de la pantalla (/sys/class/backlight/*/brightness); -1 si no hay.
std::string find_backlight_dir();
int read_brightness(const std::string& dir);
// Escribe el brillo; false si no se puede (hace falta el grupo `video`).
bool write_brightness(const std::string& dir, int value);

} // namespace platform
