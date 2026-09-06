// native/src/platform/folder_picker.mm
//
// macOS NSOpenPanel folder chooser. See folder_picker.h for the contract.

#import <AppKit/AppKit.h>

#include "folder_picker.h"

namespace dauntless::platform {

std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& message) {
    @autoreleasepool {
        // NSOpenPanel needs an NSApplication to exist, and we cannot assume
        // one does: install_macos_app() sits behind DAUNTLESS_ENABLE_CEF,
        // and this runs from the boot failure branch BEFORE r.init(), so
        // GLFW has not made one either. sharedApplication is idempotent and
        // creates it if needed.
        [NSApplication sharedApplication];

        NSOpenPanel* panel = [NSOpenPanel openPanel];
        panel.canChooseFiles = NO;
        panel.canChooseDirectories = YES;
        panel.allowsMultipleSelection = NO;
        panel.prompt = @"Choose";
        if (!title.empty()) {
            panel.title = [NSString stringWithUTF8String:title.c_str()];
        }
        if (!message.empty()) {
            panel.message = [NSString stringWithUTF8String:message.c_str()];
        }

        if ([panel runModal] != NSModalResponseOK) {
            return std::nullopt;
        }
        NSURL* url = panel.URLs.firstObject;
        if (url == nil) {
            return std::nullopt;
        }
        const char* chosen = url.fileSystemRepresentation;
        if (chosen == nullptr || *chosen == '\0') {
            return std::nullopt;
        }
        return std::string(chosen);
    }
}

}  // namespace dauntless::platform
