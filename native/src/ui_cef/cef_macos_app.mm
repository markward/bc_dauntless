// native/src/ui_cef/cef_macos_app.mm
//
// Chromium's AppKit code expects NSApp to implement `isHandlingSendEvent`
// (declared in Chromium's CrAppProtocol). Without it, closing a CEF
// window (e.g. clicking the red X on DevTools) crashes with:
//
//     -[NSApplication isHandlingSendEvent]: unrecognized selector ...
//
// This file provides a minimal NSApplication subclass that conforms to
// the protocol. Call `dauntless::ui_cef::install_macos_app()` from main()
// before any AppKit usage so [NSApplication sharedApplication] returns
// our subclass.

#import <AppKit/AppKit.h>

#include "cef_macos_app.h"

@interface DauntlessCefApplication : NSApplication
@property(nonatomic, readwrite, getter=isHandlingSendEvent) BOOL handlingSendEvent;
@end

@implementation DauntlessCefApplication
@synthesize handlingSendEvent = handlingSendEvent_;

- (void)sendEvent:(NSEvent*)event {
    BOOL wasHandling = handlingSendEvent_;
    handlingSendEvent_ = YES;
    [super sendEvent:event];
    handlingSendEvent_ = wasHandling;
}
@end

namespace dauntless::ui_cef {

void install_macos_app() {
    // Touching [DauntlessCefApplication sharedApplication] before any
    // other NSApp access installs our subclass as the global app. NSApp
    // returns this instance from then on.
    @autoreleasepool {
        [DauntlessCefApplication sharedApplication];
    }
}

}  // namespace dauntless::ui_cef
