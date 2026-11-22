/*
 * SPDX-License-Identifier: MIT
 */

#include "battery.h"

#include "process.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>

namespace platform {
namespace {

namespace fs = std::filesystem;

std::string trimmed(const std::string& path) {
    std::string s = read_text_file(path);
    while (!s.empty() && (s.back() == '\n' || s.back() == ' ' || s.back() == '\r')) {
        s.pop_back();
    }
    return s;
}

bool read_long(const std::string& path, long long& out) {
    const std::string s = trimmed(path);
    if (s.empty()) {
        return false;
    }
    char* end = nullptr;
    out = std::strtoll(s.c_str(), &end, 10);
    return end && end != s.c_str();
}

} // namespace

std::string find_battery_dir() {
    std::error_code ec;
    for (const auto& entry : fs::directory_iterator("/sys/class/power_supply", ec)) {
        if (trimmed((entry.path() / "type").string()) == "Battery") {
            return entry.path().string();
        }
    }
    return "";
}

BatteryReading read_battery(const std::string& dir) {
    BatteryReading r;
    if (dir.empty()) {
        return r;
    }
    r.status = trimmed(dir + "/status");
    r.present = !r.status.empty();
    long long v = 0;
    if (read_long(dir + "/capacity", v)) {
        r.capacity = static_cast<int>(v);
    }
    if (read_long(dir + "/voltage_now", v)) {
        r.voltage_v = v / 1e6;
    }
    if (read_long(dir + "/current_now", v)) {
        // El bq27220 da µA negativos al descargar (así lo publica el driver del kernel):
        // se invierte para que el consumo salga positivo.
        r.current_ma = -v / 1000.0;
    }
    if (read_long(dir + "/charge_now", v)) {
        r.charge_mah = v / 1000.0;
    }
    if (read_long(dir + "/charge_full", v)) {
        r.charge_full_mah = v / 1000.0;
    }
    return r;
}

std::string find_backlight_dir() {
    std::error_code ec;
    for (const auto& entry : fs::directory_iterator("/sys/class/backlight", ec)) {
        if (fs::exists(entry.path() / "brightness", ec)) {
            return entry.path().string();
        }
    }
    return "";
}

int read_brightness(const std::string& dir) {
    long long v = 0;
    if (dir.empty() || !read_long(dir + "/brightness", v)) {
        return -1;
    }
    return static_cast<int>(v);
}

bool write_brightness(const std::string& dir, int value) {
    if (dir.empty()) {
        return false;
    }
    std::FILE* f = std::fopen((dir + "/brightness").c_str(), "w");
    if (!f) {
        return false;
    }
    const bool ok = std::fprintf(f, "%d\n", value) > 0;
    return std::fclose(f) == 0 && ok;
}

} // namespace platform
