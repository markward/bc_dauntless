// native/src/platform/folder_picker.cc
//
// Fallback for platforms with no folder-chooser implementation. Compiles
// to nothing on Apple, where folder_picker.mm provides the symbol.
//
// Returning nullopt is not a stub awaiting completion so much as a
// deliberate degradation: boot treats it exactly like a cancel and prints
// the full describe_failure() diagnostic, which is the behaviour every
// platform had before this feature existed.

#include "folder_picker.h"

#ifndef __APPLE__

namespace dauntless::platform {

std::optional<std::string> pick_folder(const std::string& /*title*/,
                                       const std::string& /*message*/) {
    return std::nullopt;
}

}  // namespace dauntless::platform

#endif  // !__APPLE__
