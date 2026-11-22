/*
 * SPDX-License-Identifier: MIT
 */

#pragma once

#include <string>
#include <vector>

namespace platform {

struct ProcessResult {
    int exit_code = -1; // -1 si no se pudo lanzar o lo mató una señal
    std::string output; // stdout (y stderr, juntos)
};

// Lanza `argv[0]` (buscándolo en el PATH) con esos argumentos, sin shell: nada de lo que va
// en los argumentos se interpreta. Espera a que acabe y devuelve su salida.
ProcessResult run_process(const std::vector<std::string>& argv);

// Lee un fichero de texto entero ("" si no se puede).
std::string read_text_file(const std::string& path);

} // namespace platform
