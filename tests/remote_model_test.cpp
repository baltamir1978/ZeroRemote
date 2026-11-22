/*
 * SPDX-License-Identifier: MIT
 */

#include "remote_settings.h"

#include <cstdio>

namespace {

int failures = 0;

#define CHECK(cond)                                                      \
    do {                                                                 \
        if (!(cond)) {                                                   \
            std::printf("FALLO %s:%d  %s\n", __FILE__, __LINE__, #cond); \
            ++failures;                                                  \
        }                                                                \
    } while (0)

void test_settings() {
    // Por defecto: pantalla sí, archivos no (igual que zeroremote/config.py).
    auto s = remote::parse_settings("");
    CHECK(s.screen && !s.files);
    s = remote::parse_settings("# x\n screen = off \nfiles=on\nfiles=maybe\nbasura\n=on\n");
    CHECK(!s.screen && s.files);
    // Ida y vuelta por el texto.
    remote::Settings t;
    t.screen = false;
    t.files = true;
    const auto back = remote::parse_settings(remote::settings_text(t));
    CHECK(!back.screen && back.files);
}

void test_status() {
    auto st = remote::parse_status("");
    CHECK(!st.known);
    st = remote::parse_status(
        "listening=1\nurl=http://100.1.2.3:8320/\nscreen=on\nfiles=off\nclients=1\nlast_client=100.9.9.9\n");
    CHECK(st.known && st.listening && st.url == "http://100.1.2.3:8320/");
    CHECK(st.clients == 1 && st.last_client == "100.9.9.9");
}

void test_status_line() {
    remote::Settings on;
    remote::Settings off;
    off.screen = false;
    remote::Status st;
    CHECK(remote::status_line(st, off) == "Off: nothing is shared");
    CHECK(remote::status_line(st, on) == "Service not running");
    st.known = true;
    CHECK(remote::status_line(st, on) == "Waiting for Tailscale...");
    st.listening = true;
    CHECK(remote::status_line(st, on) == "Nobody watching");
    st.clients = 1;
    st.last_client = "100.9.9.9";
    CHECK(remote::status_line(st, on) == "Watching: 100.9.9.9");
    st.clients = 2;
    CHECK(remote::status_line(st, on) == "Watching: 2 devices");
    remote::Settings files_only;
    files_only.screen = false;
    files_only.files = true;
    st.clients = 0;
    CHECK(remote::status_line(st, files_only) == "Ready");
}

} // namespace

int main() {
    test_settings();
    test_status();
    test_status_line();
    if (failures == 0) {
        std::printf("remote_model_test: todo bien\n");
    }
    return failures == 0 ? 0 : 1;
}
