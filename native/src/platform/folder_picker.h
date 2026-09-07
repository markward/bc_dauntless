// native/src/platform/folder_picker.h
//
// Native "choose a folder" panel for the first-run path picker.
//
// std::nullopt means BOTH "the player cancelled" AND "this platform has
// no implementation". Callers must treat them identically -- that is what
// lets Windows and Linux ship with no picker and no special case: boot
// falls through to the same describe_failure() + exit 1 either way.
//
// Deliberately in `platform` rather than `ui_cef`: src/ui_cef/CMakeLists.txt
// returns early when DAUNTLESS_ENABLE_CEF is off, so anything living there
// does not exist in --no-cef builds -- precisely the builds most likely to
// be run from a bare checkout with no BC content.
#pragma once

#include <optional>
#include <string>

namespace dauntless::platform {

/// Show a modal folder chooser. Blocks until dismissed.
///
/// `title` names the window; `message` is the explanatory line inside the
/// panel. The only caller (engine/first_run.py's _default_picker, via
/// FirstRunPanel._browse) always passes "" -- the screen shows a row's
/// rejection as that row's own status/hint text instead, so there is
/// nothing left for the native panel's message to carry.
std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& message);

}  // namespace dauntless::platform
