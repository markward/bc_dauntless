// native/src/platform/exe_path.h
//
// OS-facing path helpers shared by the host binary and the CEF lifecycle.
#pragma once

#include <filesystem>
#include <string>

namespace dauntless::platform {

/// Path of the running executable.
///
/// Deliberately NOT std::filesystem::canonical(argv[0]). canonical() resolves
/// a relative path against the CURRENT DIRECTORY, so it throws whenever
/// argv[0] is a bare name and the cwd is not the executable's directory --
/// which is exactly what a launch through PATH looks like. Uncaught (and this
/// binary is built without /EHsc) that terminates the process with no message
/// whatsoever: measured exit 0xC0000409, zero bytes of output.
///
/// On Windows the OS is asked for the image path directly, which additionally
/// keeps a substituted or mapped drive letter intact instead of resolving it
/// back to its target -- canonical() rewrote "X:\dauntless.exe" to its C:\...
/// original, and CEF's own check that libcef.dll was loaded from the expected
/// path then aborted with "Found libcef.dll at unexpected path".
///
/// macOS uses _NSGetExecutablePath for the same reason (measured: a bare-name
/// launch through PATH aborted with an uncaught filesystem_error, exit 134).
/// Other POSIX still resolves argv[0], which reports rather than throws but
/// cannot answer a PATH launch -- no /proc/self/exe equivalent is used yet
/// because nothing here has been built or run on Linux.
///
/// Returns an empty path on failure, with `error` set to a message naming what
/// was tried.
std::filesystem::path executable_path(const char* argv0, std::string& error);

/// std::filesystem::canonical that reports instead of throwing. Returns an
/// empty path on failure, with `error` set to a message naming the path.
std::filesystem::path canonical_or_error(const std::filesystem::path& path,
                                         std::string& error);

}  // namespace dauntless::platform
