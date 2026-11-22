/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include "base_screen.h"
#include "remote_settings.h"

#include <array>
#include <string>

namespace screen {

/**
 * La pantalla de Remote: el código QR con la dirección de la web (para abrirla con la cámara
 * del móvil) y los dos interruptores del servicio, pantalla remota y compartir archivos.
 * F/X eligen interruptor; ENTER, Z o C lo cambian. Los interruptores se guardan en
 * ~/.config/zeroremote/remote.conf, que el servicio vigila (y que la web también cambia: se
 * relee cada medio segundo, con el fichero de estado del servicio).
 */
class HomeScreen : public BaseScreen {
public:
    HomeScreen(viewmodel::BaseViewModel& view_model, app::AssetManager& assets);
    ~HomeScreen() override;

protected:
    void build_content(lv_obj_t* content) override;

private:
    static constexpr int kRows = 2;

    bool handle_key(uint32_t key);
    void toggle_selected();
    void save_settings();
    void poll_status();
    void refresh();

    static void timer_cb(lv_timer_t* timer);
    static void theme_observer_cb(lv_observer_t* observer, lv_subject_t* subject);

    remote::Settings settings_;
    remote::Status status_;
    std::string qr_url_; // lo que hay pintado en el QR, para no regenerarlo cada vez
    std::string save_error_;
    int row_ = 0;

    lv_obj_t* qr_ = nullptr;
    lv_obj_t* qr_placeholder_ = nullptr;
    std::array<lv_obj_t*, kRows> row_boxes_{};
    std::array<lv_obj_t*, kRows> row_titles_{};
    std::array<lv_obj_t*, kRows> row_switches_{};
    lv_obj_t* url_ = nullptr;
    lv_obj_t* status_label_ = nullptr;
    lv_obj_t* hint_ = nullptr;
    lv_timer_t* timer_ = nullptr;
};

} // namespace screen
