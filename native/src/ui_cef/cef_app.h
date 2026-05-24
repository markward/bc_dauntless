// native/src/ui_cef/cef_app.h
//
// CefApp implementation: applies process-wide Chromium command-line
// switches via OnBeforeCommandLineProcessing. These switches MUST hit
// the browser process — without them macOS shows a Keychain password
// prompt and a Notifications permission prompt at every launch.

#pragma once

#include "include/cef_app.h"

namespace dauntless::ui_cef {

class DauntlessCefApp : public CefApp, public CefBrowserProcessHandler {
public:
    DauntlessCefApp() = default;

    CefRefPtr<CefBrowserProcessHandler> GetBrowserProcessHandler() override {
        return this;
    }

    void OnBeforeCommandLineProcessing(
        const CefString& process_type,
        CefRefPtr<CefCommandLine> command_line) override;

private:
    IMPLEMENT_REFCOUNTING(DauntlessCefApp);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefApp);
};

}  // namespace dauntless::ui_cef
