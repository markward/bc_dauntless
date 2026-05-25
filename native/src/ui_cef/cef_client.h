// native/src/ui_cef/cef_client.h
//
// CefClient + CefRenderHandler + CefLifeSpanHandler + CefDisplayHandler.
// CEF calls OnPaint each time the browser produces a new bitmap; we
// cache it for the next composite. CEF runs in single-threaded
// message-loop mode (see cef_lifecycle.cc), so OnPaint arrives on the
// main thread between pump() and composite() — no mutex.
//
// OnConsoleMessage is the JS→C++ event channel: JS emits
// `console.info("dauntless-event:" + name)`, this client recognises
// the prefix and forwards the event name to whatever callback the
// host (Python via pybind) registered via
// `cef_lifecycle::set_event_handler`. Using console messages
// sidesteps Chromium's scheme/navigation policies — every
// console.* call reaches OnConsoleMessage regardless of how CEF is
// configured, and DevTools makes it trivially debuggable.

#pragma once

#include "include/cef_client.h"
#include "include/cef_display_handler.h"
#include "include/cef_render_handler.h"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace dauntless::ui_cef {

class DauntlessCefClient : public CefClient,
                           public CefRenderHandler,
                           public CefLifeSpanHandler,
                           public CefDisplayHandler {
public:
    DauntlessCefClient(int view_width, int view_height);

    // CefClient
    CefRefPtr<CefRenderHandler>   GetRenderHandler()   override { return this; }
    CefRefPtr<CefLifeSpanHandler> GetLifeSpanHandler() override { return this; }
    CefRefPtr<CefDisplayHandler>  GetDisplayHandler()  override { return this; }

    // CefRenderHandler
    void GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) override;
    void OnPaint(CefRefPtr<CefBrowser> browser,
                 PaintElementType type,
                 const RectList& dirtyRects,
                 const void* buffer,
                 int width, int height) override;

    // CefLifeSpanHandler — stores the browser handle for toggle_devtools / reload.
    void OnAfterCreated(CefRefPtr<CefBrowser> browser) override;
    void OnBeforeClose(CefRefPtr<CefBrowser> browser) override;

    // CefDisplayHandler — JS→C++ event channel via console.* messages
    // with a "dauntless-event:" prefix.
    bool OnConsoleMessage(CefRefPtr<CefBrowser> browser,
                          cef_log_severity_t level,
                          const CefString& message,
                          const CefString& source,
                          int line) override;

    // Returns nullptr if no bitmap has arrived yet.
    const std::uint8_t* latest_bitmap(int* out_width, int* out_height) const;

    CefRefPtr<CefBrowser> browser() const { return browser_; }

    // Event-handler injection. cef_lifecycle::set_event_handler routes
    // the host-supplied callback through here. Invoked on the main
    // thread (single-threaded message-loop mode), so no synchronisation
    // is required.
    void set_event_handler(std::function<void(const std::string&)> handler);

private:
    int view_width_;
    int view_height_;

    std::vector<std::uint8_t> bitmap_;
    int bitmap_width_  = 0;
    int bitmap_height_ = 0;
    bool ready_ = false;

    CefRefPtr<CefBrowser> browser_;

    std::function<void(const std::string&)> event_handler_;

    IMPLEMENT_REFCOUNTING(DauntlessCefClient);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefClient);
};

}  // namespace dauntless::ui_cef
