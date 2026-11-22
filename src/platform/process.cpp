/*
 * SPDX-License-Identifier: MIT
 */

#include "process.h"

#include <fstream>
#include <sstream>

#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

namespace platform {

ProcessResult run_process(const std::vector<std::string>& argv) {
    ProcessResult result;
    if (argv.empty()) {
        return result;
    }
    int pipefd[2];
    if (::pipe2(pipefd, O_CLOEXEC) != 0) {
        return result;
    }
    // Todo lo que reserva memoria, antes del fork (la app tiene hilos).
    std::vector<char*> args;
    args.reserve(argv.size() + 1);
    for (const auto& a : argv) {
        args.push_back(const_cast<char*>(a.c_str()));
    }
    args.push_back(nullptr);

    const pid_t pid = ::fork();
    if (pid < 0) {
        ::close(pipefd[0]);
        ::close(pipefd[1]);
        return result;
    }
    if (pid == 0) {
        ::dup2(pipefd[1], STDOUT_FILENO);
        ::dup2(pipefd[1], STDERR_FILENO);
        const int devnull = ::open("/dev/null", O_RDONLY);
        if (devnull >= 0) {
            ::dup2(devnull, STDIN_FILENO);
        }
        ::execvp(args[0], args.data());
        ::_exit(127);
    }
    ::close(pipefd[1]);
    char buf[512];
    ssize_t n;
    while ((n = ::read(pipefd[0], buf, sizeof(buf))) > 0) {
        result.output.append(buf, static_cast<std::size_t>(n));
    }
    ::close(pipefd[0]);
    int status = 0;
    if (::waitpid(pid, &status, 0) == pid && WIFEXITED(status)) {
        result.exit_code = WEXITSTATUS(status);
    }
    return result;
}

std::string read_text_file(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        return "";
    }
    std::ostringstream out;
    out << in.rdbuf();
    return out.str();
}

} // namespace platform
