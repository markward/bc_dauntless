// native/src/ui_cef/cef_app.cc
#include "cef_app.h"

namespace dauntless::ui_cef {

void DauntlessCefApp::OnBeforeCommandLineProcessing(
    const CefString& process_type,
    CefRefPtr<CefCommandLine> command_line) {
    // Apply lockdown only in the browser process. Helpers inherit a copy
    // of these via CEF's internal command-line propagation.
    if (!process_type.empty()) return;

    // Force software GPU inside CEF's GPU process. CEF's GPU process
    // would otherwise conflict with our GLFW-managed OpenGL context
    // (shared IOSurface allocations on macOS in particular).
    command_line->AppendSwitch("disable-gpu");
    command_line->AppendSwitch("disable-gpu-compositing");

    // Stops the macOS Keychain "Chromium Safe Storage" password prompt.
    // We do not persist user data, so a plaintext backend + mock keychain
    // are appropriate.
    command_line->AppendSwitchWithValue("password-store", "basic");
    command_line->AppendSwitch("use-mock-keychain");

    // Stops the macOS Notifications permission prompt. The HTML5
    // `--disable-notifications` switch alone leaves macOS's NATIVE
    // NSUserNotificationCenter registration active, which is what
    // actually triggers the OS permission dialog. Both are required.
    command_line->AppendSwitch("disable-notifications");
    command_line->AppendSwitchWithValue(
        "disable-features",
        "NativeNotifications,SystemNotifications,UNNotifications");

    // Allow file:// ship_status.html to load sibling assets (panel CSS/JS,
    // ship-icon PNGs under icons/ships/, fonts, etc.). Chromium treats
    // each file:// URL as a unique origin by default, so without this
    // switch <img src="icons/ships/Galaxy.png"> requests are silently
    // blocked as cross-origin even though the file lives next to the
    // host page. Safe here because we never load remote content into
    // this browser instance.
    command_line->AppendSwitch("allow-file-access-from-files");
}

}  // namespace dauntless::ui_cef
