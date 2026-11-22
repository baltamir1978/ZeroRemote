/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include "app_page.h"
#include "subjects.h"

#include "lvgl.h"

#include <functional>

namespace viewmodel {

/**
 * Estado de la app tal como lo ve la pantalla. Remote es una sola pantalla (Home), que
 * registra sus propias teclas.
 *
 * Aquí viven la navegación entre páginas y la selección del menú.
 */
class BaseViewModel {
public:
    // Entradas del menú Home, en orden de aparición.
    static constexpr int kMenuCount = 1;

    BaseViewModel();
    ~BaseViewModel();

    BaseViewModel(const BaseViewModel&) = delete;
    BaseViewModel& operator=(const BaseViewModel&) = delete;

    lv_subject_t* title_subject();
    lv_subject_t* dark_mode_subject();
    lv_subject_t* current_page_subject();
    lv_subject_t* quit_requested_subject();
    /** Índice de la entrada resaltada en el menú Home (0..kMenuCount-1). */
    lv_subject_t* menu_index_subject();

    bool is_dark_mode() const;
    void set_dark_mode(bool enabled);
    void toggle_dark_mode();

    int menu_index() const;
    model::AppPage current_page() const;
    /** Ir a una página y poner su título. */
    void go_to(model::AppPage page);

    /** Tecla que no es ESC. Devuelve si se ha usado. */
    bool handle_key(uint32_t key);

    /**
     * ESC corto: volver atrás. En una herramienta vuelve a Home; en Home devuelve `false`
     * (y entonces la app recuerda que para salir hay que mantener ESC).
     */
    bool back();

    void request_quit();

    // Una pantalla de herramienta se registra para recibir las teclas y el «atrás» mientras
    // está montada (y se da de baja al destruirse). `key_handler` devuelve si usó la tecla;
    // `back_handler` devuelve true si gestionó el «atrás» y hay que quedarse en la pantalla
    // (p. ej. parar una grabación), o false para que se vuelva al menú.
    using KeyHandler = std::function<bool(uint32_t)>;
    using BackHandler = std::function<bool()>;
    // `owner` es la pantalla: sólo quien los puso los puede quitar.
    void set_page_handlers(const void* owner, KeyHandler key_handler, BackHandler back_handler);
    void clear_page_handlers(const void* owner);

private:
    void move_selection(int delta);
    // Página que corresponde a la entrada `index` del menú Home.
    static model::AppPage page_for_menu(int index);

    reactive::StringSubject<64> title_subject_;
    reactive::BoolSubject dark_mode_subject_;
    reactive::IntSubject current_page_subject_;
    reactive::BoolSubject quit_requested_subject_;
    reactive::IntSubject menu_index_subject_;

    const void* page_handlers_owner_ = nullptr;
    KeyHandler page_key_handler_;
    BackHandler page_back_handler_;
};

} // namespace viewmodel
