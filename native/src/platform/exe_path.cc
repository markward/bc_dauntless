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

#ifdef __APPLE__
#include <mach-o/dyld.h>

#include <cstdint>
#include <cstring>
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
#elif defined(__APPLE__)
    (void)argv0;  // the OS knows the image path; argv[0] is only a hint
    // The macOS counterpart of GetModuleFileNameW. Asking the kernel is what
    // actually fixes a launch through PATH -- resolving argv[0] against the
    // cwd cannot, because on that launch the name does not exist there at all.
    //
    // _NSGetExecutablePath reports the required size (including the NUL) via
    // its in/out length argument when the buffer is too small, so probe with a
    // one-byte buffer, then allocate and ask again. A nullptr buffer is not
    // documented as accepted, so it is not used to probe.
    std::uint32_t size = 1;
    char probe = '\0';
    if (_NSGetExecutablePath(&probe, &size) == 0) {
        error = "_NSGetExecutablePath returned an empty image path";
        return {};
    }
    std::string buf(size, '\0');
    if (_NSGetExecutablePath(buf.data(), &size) != 0) {
        error = "_NSGetExecutablePath failed for a buffer of its own "
                "requested size (" + std::to_string(size) + " bytes)";
        return {};
    }
    buf.resize(std::strlen(buf.c_str()));  // the reported size counts the NUL
    const std::filesystem::path image_path(buf);

    // The path is absolute but explicitly not guaranteed canonical: it can
    // carry symlinks and "..". Resolve those so callers comparing it against,
    // or hanging sibling paths off, the build directory get the real location.
    // A failure here is not fatal -- the unresolved path is still a valid,
    // absolute path to this binary, which beats refusing to start.
    std::error_code ec;
    std::filesystem::path resolved = std::filesystem::canonical(image_path, ec);
    return ec ? image_path : resolved;
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
