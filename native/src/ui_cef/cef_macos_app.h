// native/src/ui_cef/cef_macos_app.h
//
// macOS-only NSApplication subclass installer (see .mm file for context).
// No-op on other platforms; safe to call unconditionally from main().

#pragma once

namespace dauntless::ui_cef {

#ifdef __APPLE__
void install_macos_app();
#else
inline void install_macos_app() {}
#endif

}  // namespace dauntless::ui_cef
