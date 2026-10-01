// native/src/platform/relaunch.cc
#include "platform/relaunch.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <optional>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace dauntless::platform {

namespace {
std::optional<std::vector<std::string>>& pending() {
    static std::optional<std::vector<std::string>> p;
    return p;
}
}  // namespace

void set_relaunch_request(std::vector<std::string> extra_args) {
    pending() = std::move(extra_args);
}

bool take_relaunch_request(std::vector<std::string>* extra_args) {
    if (!pending()) return false;
    *extra_args = std::move(*pending());
    pending().reset();
    return true;
}

std::vector<std::string> build_relaunch_argv(const std::string& exe,
                                             const std::vector<std::string>& original_args,
                                             const std::vector<std::string>& extra_args) {
    std::vector<std::string> out{exe};
    for (const auto& a : original_args) {
        if (std::find(extra_args.begin(), extra_args.end(), a) == extra_args.end()) out.push_back(a);
    }
    out.insert(out.end(), extra_args.begin(), extra_args.end());
    return out;
}

int relaunch(const std::vector<std::string>& argv, std::string& error) {
    if (argv.empty()) { error = "empty argv"; return -1; }
    std::vector<char*> raw;
    for (const auto& a : argv) raw.push_back(const_cast<char*>(a.c_str()));
    raw.push_back(nullptr);
#ifdef _WIN32
    if (_spawnv(_P_NOWAIT, raw[0], raw.data()) == -1) {
        error = std::string("_spawnv: ") + std::strerror(errno);
        return -1;
    }
    return 0;
#else
    execv(raw[0], raw.data());
    error = std::string("execv: ") + std::strerror(errno);
    return -1;
#endif
}

}  // namespace dauntless::platform
