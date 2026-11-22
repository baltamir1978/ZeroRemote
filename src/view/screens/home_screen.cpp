/*
 * SPDX-License-Identifier: MIT
 */

#include "home_screen.h"

#include "asset_manager.h"
#include "theme.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <system_error>
#include <unistd.h>

namespace screen {
namespace {

namespace fs = std::filesystem;

constexpr int32_t kQrSize = 112;
constexpr int32_t kQrX = 8;
constexpr int32_t kQrY = 10;
constexpr int32_t kColX = 134;
constexpr int32_t kColW = view::kScreenWidth - kColX - 8;
constexpr int32_t kRowH = 24;
constexpr int32_t kRowGap = 4;
constexpr int32_t kRowsY = 8;

constexpr const char* kTitles[] = {"Remote screen", "File sharing"};

// Verde de «encendido» de iOS, como en ZeroPower: se reconoce al momento con los dos temas.
const lv_color_t kSwitchOn = lv_color_hex(0x34C759);

std::string config_path() {
    const char* xdg = std::getenv("XDG_CONFIG_HOME");
    const char* home = std::getenv("HOME");
    const std::string base = (xdg && *xdg) ? xdg : std::string(home ? home : "/tmp") + "/.config";
    return base + "/zeroremote/remote.conf";
}

std::string status_path() {
    const char* run = std::getenv("XDG_RUNTIME_DIR");
    const std::string base = (run && *run) ? run : "/run/user/" + std::to_string(::getuid());
    return base + "/zeroremote/status";
}

std::string read_file(const std::string& path) {
    std::ifstream in(path);
    std::stringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void set_text(lv_obj_t* label, const std::string& text) {
    const char* current = lv_label_get_text(label);
    if (!current || text != current) {
        lv_label_set_text(label, text.c_str());
    }
}

} // namespace

HomeScreen::HomeScreen(viewmodel::BaseViewModel& view_model, app::AssetManager& assets)
    : BaseScreen(view_model, assets), settings_(remote::parse_settings(read_file(config_path()))) {
    init();
    this->view_model().set_page_handlers(this, [this](uint32_t key) { return handle_key(key); },
                                         []() { return false; });
}

HomeScreen::~HomeScreen() {
    view_model().clear_page_handlers(this);
    if (timer_) {
        lv_timer_delete(timer_);
    }
}

void HomeScreen::build_content(lv_obj_t* content) {
    lv_obj_remove_flag(content, LV_OBJ_FLAG_SCROLLABLE);
    const lv_font_t* title_font = assets().load_standard_font(13);
    const lv_font_t* text_font = assets().load_standard_font(12, app::StandardFontWeight::Regular);
    const lv_font_t* small = assets().load_standard_font(11, app::StandardFontWeight::Regular);
    const lv_font_t* big = assets().load_standard_font(16);

    // QR: negro sobre blanco con su margen, sea cual sea el tema, o la cámara no lo lee.
    qr_ = lv_qrcode_create(content);
    lv_qrcode_set_size(qr_, kQrSize);
    lv_qrcode_set_dark_color(qr_, lv_color_black());
    lv_qrcode_set_light_color(qr_, lv_color_white());
    lv_qrcode_set_quiet_zone(qr_, true);
    lv_obj_set_pos(qr_, kQrX, kQrY);
    lv_obj_add_flag(qr_, LV_OBJ_FLAG_HIDDEN);

    qr_placeholder_ = lv_label_create(content);
    lv_obj_set_style_text_font(qr_placeholder_, big ? big : &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_align(qr_placeholder_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_width(qr_placeholder_, kQrSize);
    lv_obj_set_pos(qr_placeholder_, kQrX, kQrY + kQrSize / 2 - 10);

    for (int i = 0; i < kRows; ++i) {
        auto* box = lv_obj_create(content);
        lv_obj_remove_style_all(box);
        lv_obj_set_size(box, kColW, kRowH);
        lv_obj_set_pos(box, kColX, kRowsY + i * (kRowH + kRowGap));
        lv_obj_set_style_radius(box, 5, 0);
        lv_obj_set_style_bg_opa(box, LV_OPA_COVER, 0);
        lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
        row_boxes_[i] = box;

        row_titles_[i] = lv_label_create(box);
        lv_label_set_text(row_titles_[i], kTitles[i]);
        lv_obj_set_style_text_font(row_titles_[i], title_font ? title_font : &lv_font_montserrat_12, 0);
        lv_obj_align(row_titles_[i], LV_ALIGN_LEFT_MID, 7, 0);

        auto* sw = lv_switch_create(box);
        lv_obj_set_size(sw, 32, 16);
        lv_obj_align(sw, LV_ALIGN_RIGHT_MID, -6, 0);
        lv_obj_remove_flag(sw, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_style_anim_duration(sw, 0, 0);
        lv_obj_set_style_bg_color(sw, lv_color_hex(0x8E8E93), LV_PART_MAIN);
        lv_obj_set_style_bg_opa(sw, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_bg_color(sw, kSwitchOn, LV_PART_INDICATOR | LV_STATE_CHECKED);
        lv_obj_set_style_bg_color(sw, lv_color_white(), LV_PART_KNOB);
        lv_obj_set_style_pad_all(sw, -2, LV_PART_KNOB);
        row_switches_[i] = sw;
    }

    url_ = lv_label_create(content);
    lv_obj_set_style_text_font(url_, text_font ? text_font : &lv_font_montserrat_12, 0);
    lv_label_set_long_mode(url_, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(url_, kColW);
    lv_obj_set_pos(url_, kColX + 2, kRowsY + kRows * (kRowH + kRowGap) + 4);

    status_label_ = lv_label_create(content);
    lv_obj_set_style_text_font(status_label_, text_font ? text_font : &lv_font_montserrat_12, 0);
    lv_label_set_long_mode(status_label_, LV_LABEL_LONG_DOT);
    lv_obj_set_width(status_label_, kColW);
    lv_obj_set_pos(status_label_, kColX + 2, kRowsY + kRows * (kRowH + kRowGap) + 22);

    hint_ = lv_label_create(content);
    lv_obj_set_style_text_font(hint_, small ? small : &lv_font_montserrat_12, 0);
    lv_label_set_text(hint_, "F/X choose   ENTER switch");
    lv_obj_set_pos(hint_, kColX + 2, kQrY + kQrSize - 12);

    lv_subject_add_observer_obj(view_model().dark_mode_subject(), theme_observer_cb, content, this);
    timer_ = lv_timer_create(timer_cb, 500, this);
    poll_status();
}

bool HomeScreen::handle_key(uint32_t key) {
    switch (key) {
        case LV_KEY_UP:
        case 'f':
        case 'F':
        case LV_KEY_DOWN:
        case 'x':
        case 'X':
            row_ = (row_ + 1) % kRows; // dos filas: arriba y abajo hacen lo mismo
            refresh();
            return true;
        case LV_KEY_ENTER:
        case '\r':
        case ' ':
        case LV_KEY_LEFT:
        case LV_KEY_RIGHT:
        case 'z':
        case 'Z':
        case 'c':
        case 'C':
            toggle_selected();
            return true;
        default:
            return false;
    }
}

void HomeScreen::toggle_selected() {
    if (row_ == 0) {
        settings_.screen = !settings_.screen;
    } else {
        settings_.files = !settings_.files;
    }
    save_settings();
    refresh();
}

void HomeScreen::save_settings() {
    // Temporal + rename: el servicio nunca lee un fichero a medias.
    const fs::path path(config_path());
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    const std::string tmp = path.string() + ".tmp";
    {
        std::ofstream out(tmp, std::ios::trunc);
        out << remote::settings_text(settings_);
        if (!out) {
            save_error_ = "Cannot save the switches";
            return;
        }
    }
    fs::rename(tmp, path, ec);
    save_error_ = ec ? "Cannot save the switches" : "";
}

void HomeScreen::poll_status() {
    status_ = remote::parse_status(read_file(status_path()));
    // Los interruptores también se cambian desde la web: se releen para enseñarlos al día y
    // para que el siguiente cambio aquí no pise el de la web con un valor viejo.
    settings_ = remote::parse_settings(read_file(config_path()));
    refresh();
}

void HomeScreen::refresh() {
    if (!hint_) {
        return; // primer aviso de un observador, con la pantalla a medio montar
    }
    const auto colors = view::palette(view_model().is_dark_mode());
    const bool values[kRows] = {settings_.screen, settings_.files};

    for (int i = 0; i < kRows; ++i) {
        const bool selected = i == row_;
        lv_obj_set_style_bg_color(row_boxes_[i], selected ? colors.primary : colors.surface, 0);
        lv_obj_set_style_text_color(row_titles_[i], selected ? colors.background : colors.text, 0);
        if (values[i]) {
            lv_obj_add_state(row_switches_[i], LV_STATE_CHECKED);
        } else {
            lv_obj_remove_state(row_switches_[i], LV_STATE_CHECKED);
        }
    }

    // El QR sólo cuando hay algo que abrir; si no, un aviso en su sitio.
    const bool any = settings_.screen || settings_.files;
    const bool show_qr = any && status_.listening && !status_.url.empty();
    if (show_qr && status_.url != qr_url_) {
        lv_qrcode_update(qr_, status_.url.data(), static_cast<uint32_t>(status_.url.size()));
        qr_url_ = status_.url;
    }
    if (show_qr) {
        lv_obj_remove_flag(qr_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(qr_placeholder_, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(qr_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(qr_placeholder_, LV_OBJ_FLAG_HIDDEN);
        set_text(qr_placeholder_, any ? "..." : "Off");
    }
    lv_obj_set_style_text_color(qr_placeholder_, colors.text_disabled, 0);

    // La dirección, sin «http://» ni la barra final: cabe en una línea y se lee mejor.
    std::string url = show_qr ? status_.url : "";
    if (url.rfind("http://", 0) == 0) {
        url = url.substr(7);
    }
    if (!url.empty() && url.back() == '/') {
        url.pop_back();
    }
    set_text(url_, show_qr ? url : (any ? "Starting..." : "Turn a switch on to share"));
    lv_obj_set_style_text_color(url_, show_qr ? colors.text : colors.text_disabled, 0);

    const std::string line = save_error_.empty() ? remote::status_line(status_, settings_) : save_error_;
    set_text(status_label_, line);
    lv_obj_set_style_text_color(status_label_,
                                !save_error_.empty() ? colors.error
                                : (any && status_.clients > 0) ? colors.success
                                                      : colors.text_disabled,
                                0);
    lv_obj_set_style_text_color(hint_, colors.text_disabled, 0);
}

void HomeScreen::timer_cb(lv_timer_t* timer) {
    auto* self = static_cast<HomeScreen*>(lv_timer_get_user_data(timer));
    if (self) {
        self->poll_status();
    }
}

void HomeScreen::theme_observer_cb(lv_observer_t* observer, lv_subject_t*) {
    auto* self = static_cast<HomeScreen*>(lv_observer_get_user_data(observer));
    if (self) {
        self->refresh();
    }
}

} // namespace screen
