// native/src/platform/folder_picker.cc
//
// Folder chooser for platforms without a native-toolkit implementation.
// Compiles to nothing on Apple (folder_picker.mm provides the symbol) and on
// Windows (folder_picker_win.cc).
//
// Linux has no toolkit of its own here (GLFW opens the window, CEF draws the
// UI), so the chooser is the desktop's: zenity (GTK/GNOME) first, then
// kdialog (KDE). Each runs as a child process and prints the chosen path on
// stdout with exit status 0; a cancel exits non-zero. If neither tool is
// installed, the result is nullopt -- the same deliberate degradation every
// other unsupported platform gets: boot treats it exactly like a cancel and
// prints the full describe_failure() diagnostic.

#include "folder_picker.h"

#if !defined(__APPLE__) && !defined(_WIN32)

#include <cstdio>
#include <cstdlib>
#include <sys/wait.h>

namespace dauntless::platform {

namespace {

// Wrap `s` in single quotes for /bin/sh, closing and re-opening the quote
// around each embedded single quote.
std::string shell_quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out += c;
    }
    out += "'";
    return out;
}

// Run `cmd`, returning its stdout (trailing newlines trimmed) if it exited
// with status 0 and printed something, else nullopt.
std::optional<std::string> run_chooser(const std::string& cmd) {
    FILE* pipe = ::popen(cmd.c_str(), "r");
    if (!pipe) return std::nullopt;
    std::string out;
    char buf[512];
    while (std::fgets(buf, sizeof buf, pipe)) out += buf;
    const int status = ::pclose(pipe);
    if (status == -1 || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return std::nullopt;
    }
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r')) {
        out.pop_back();
    }
    if (out.empty()) return std::nullopt;
    return out;
}

bool have(const char* tool) {
    const std::string cmd =
        std::string("command -v ") + tool + " >/dev/null 2>&1";
    return std::system(cmd.c_str()) == 0;
}

}  // namespace

std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& /*message*/) {
    // Only the first tool found runs: a cancel in zenity must not pop up
    // kdialog as a second, surprise dialog.
    if (have("zenity")) {
        return run_chooser("zenity --file-selection --directory --title=" +
                           shell_quote(title) + " 2>/dev/null");
    }
    if (have("kdialog")) {
        return run_chooser("kdialog --getexistingdirectory ~ --title " +
                           shell_quote(title) + " 2>/dev/null");
    }
    std::fprintf(stderr,
                 "dauntless: no folder chooser found (install zenity or "
                 "kdialog), or pass --game-dir / --sdk-dir instead.\n");
    return std::nullopt;
}

}  // namespace dauntless::platform

#endif  // !__APPLE__ && !_WIN32
