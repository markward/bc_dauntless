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

std::string quote_windows_arg(const std::string& arg) {
    if (!arg.empty() && arg.find_first_of(" \t\"") == std::string::npos) return arg;
    std::string out = "\"";
    size_t backslashes = 0;
    for (char c : arg) {
        if (c == '\\') {
            ++backslashes;
            continue;
        }
        if (c == '"') {
            out.append(backslashes * 2 + 1, '\\');   // each run doubled, plus the quote's escape
        } else {
            out.append(backslashes, '\\');           // not before a quote: literal
        }
        backslashes = 0;
        out.push_back(c);
    }
    out.append(backslashes * 2, '\\');               // they precede the closing quote
    out.push_back('"');
    return out;
}

int relaunch(const std::vector<std::string>& argv, std::string& error) {
    if (argv.empty()) { error = "empty argv"; return -1; }
#ifdef _WIN32
    // _spawnv joins argv with spaces and does not quote, so a
    // `--game-dir "C:\Program Files (x86)\..."` would split; quote each arg.
    // raw[0] doubles as the exe path, so it keeps the unquoted spelling.
    std::vector<std::string> quoted;
    for (const auto& a : argv) quoted.push_back(quote_windows_arg(a));
    std::vector<char*> raw;
    for (const auto& a : quoted) raw.push_back(const_cast<char*>(a.c_str()));
    raw.push_back(nullptr);
    if (_spawnv(_P_NOWAIT, argv[0].c_str(), raw.data()) == -1) {
        error = std::string("_spawnv: ") + std::strerror(errno);
        return -1;
    }
    return 0;
#else
    std::vector<char*> raw;
    for (const auto& a : argv) raw.push_back(const_cast<char*>(a.c_str()));
    raw.push_back(nullptr);
    execv(raw[0], raw.data());
    error = std::string("execv: ") + std::strerror(errno);
    return -1;
#endif
}

}  // namespace dauntless::platform
