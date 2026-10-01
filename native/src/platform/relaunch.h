// native/src/platform/relaunch.h
//
// "Quit and Manage Mods": Python records a request during the game; host_main
// performs it AFTER Py_FinalizeEx (CEF and the window are already down), by
// re-executing itself with the original arguments plus the request's.
#pragma once

#include <string>
#include <vector>

namespace dauntless::platform {

void set_relaunch_request(std::vector<std::string> extra_args);
bool take_relaunch_request(std::vector<std::string>* extra_args);

/// {exe, original args minus any that appear in extra_args, extra args}.
std::vector<std::string> build_relaunch_argv(const std::string& exe,
                                             const std::vector<std::string>& original_args,
                                             const std::vector<std::string>& extra_args);

/// `arg` quoted so the MSVC runtime's CommandLineToArgvW rules parse it back
/// as one argument: wrapped in quotes when empty or holding a space, tab or
/// quote; embedded quotes escaped; backslashes doubled only where they
/// precede a quote (embedded or closing). Pure, so it builds and is tested
/// on every platform; only Windows' relaunch() uses it (_spawnv joins argv
/// with spaces and does not quote).
std::string quote_windows_arg(const std::string& arg);

/// POSIX: execv (returns only on failure, -1, with `error` set).
/// Windows: _spawnv(_P_NOWAIT) then returns 0 (the caller exits).
int relaunch(const std::vector<std::string>& argv, std::string& error);

}  // namespace dauntless::platform
