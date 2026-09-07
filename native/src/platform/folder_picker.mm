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
        // one does: install_macos_app() sits behind DAUNTLESS_ENABLE_CEF, and
        // while this now runs AFTER both r.init() (GLFW) and cef_initialize()
        // have had their chance to create one, a bundle-less process launched
        // straight from a terminal is not guaranteed to be a foreground app
        // even so -- and a `--no-cef` build never calls install_macos_app()
        // at all. sharedApplication is idempotent and creates it if needed,
        // so calling it unconditionally here is still correct regardless of
        // what ran before this point.
        NSApplication* app = [NSApplication sharedApplication];

        // A bundle-less, non-foreground process can be left in an activation
        // policy where no window may become key -- the panel would then open
        // behind the launching terminal with no menu bar, which to a
        // first-time player reads as the game hanging on launch. Both calls
        // are idempotent and harmless if CEF or GLFW already made us a
        // foreground app.
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        [app activateIgnoringOtherApps:YES];

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
