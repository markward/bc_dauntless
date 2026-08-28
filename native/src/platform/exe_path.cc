// native/src/platform/exe_path.cc
#include "exe_path.h"

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <vector>
#endif

#include <system_error>

namespace dauntless::platform {

std::filesystem::path executable_path(const char* argv0, std::string& error) {
    error.clear();
#ifdef _WIN32
    (void)argv0;  // the OS knows the image path; argv[0] is only a hint
    std::vector<wchar_t> buf(MAX_PATH);
    for (;;) {
        const DWORD n =
            ::GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
        if (n == 0) {
            error = "GetModuleFileNameW failed (GetLastError=" +
                    std::to_string(::GetLastError()) + ")";
            return {};
        }
        // On truncation the return value equals the buffer size (and
        // GetLastError is ERROR_INSUFFICIENT_BUFFER on older Windows), so grow
        // and retry rather than silently using a cut-off path.
        if (n < buf.size()) {
            return std::filesystem::path(std::wstring(buf.data(), n));
        }
        buf.resize(buf.size() * 2);
    }
#else
    if (argv0 == nullptr || *argv0 == '\0') {
        error = "argv[0] is empty, so the executable path cannot be resolved";
        return {};
    }
    std::error_code ec;
    std::filesystem::path resolved = std::filesystem::canonical(argv0, ec);
    if (ec) {
        error = std::string("cannot resolve argv[0] \"") + argv0 +
                "\" against the current directory: " + ec.message();
        return {};
    }
    return resolved;
#endif
}

std::filesystem::path canonical_or_error(const std::filesystem::path& path,
                                         std::string& error) {
    error.clear();
    std::error_code ec;
    std::filesystem::path resolved = std::filesystem::canonical(path, ec);
    if (ec) {
        error = "cannot resolve \"" + path.string() + "\": " + ec.message();
        return {};
    }
    return resolved;
}

}  // namespace dauntless::platform
