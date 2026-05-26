// native/src/ui_cef/cef_client.h
//
// CefClient + CefRenderHandler + CefLifeSpanHandler + CefDisplayHandler
// + CefLoadHandler.
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
//
// OnLoadEnd fires once the main frame finishes loading hello.html.
// The panel layer subscribes via cef_lifecycle::set_load_end_handler
// so it can invalidate snapshot caches once the page is ready.

#pragma once

#include "include/cef_client.h"
#include "include/cef_display_handler.h"
#include "include/cef_load_handler.h"
#include "include/cef_render_handler.h"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace dauntless::ui_cef {

class DauntlessCefClient : public CefClient,
                           public CefRenderHandler,
                           public CefLifeSpanHandler,
                           public CefDisplayHandler,
                           public CefLoadHandler {
public:
    DauntlessCefClient(int view_width, int view_height);

    // CefClient
    CefRefPtr<CefRenderHandler>   GetRenderHandler()   override { return this; }
    CefRefPtr<CefLifeSpanHandler> GetLifeSpanHandler() override { return this; }
    CefRefPtr<CefDisplayHandler>  GetDisplayHandler()  override { return this; }
    CefRefPtr<CefLoadHandler>     GetLoadHandler()     override { return this; }

    // CefRenderHandler
    void GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) override;
    bool GetScreenInfo(CefRefPtr<CefBrowser> browser, CefScreenInfo& info) override;
    void OnPaint(CefRefPtr<CefBrowser> browser,
                 PaintElementType type,
                 const RectList& dirtyRects,
                 const void* buffer,
                 int width, int height) override;

    // Tell CEF the device-pixel ratio (1.0 on non-Retina, 2.0 on Retina).
    // Must be set BEFORE the browser is created. With a non-1.0 value
    // CEF renders fonts and graphics at width*dsf × height*dsf so the
    // composite pass can blit 1:1 to a high-DPI framebuffer instead of
    // bilinear-upscaling a low-resolution bitmap.
    void set_device_scale_factor(float dsf) { device_scale_factor_ = dsf; }

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

    // CefLoadHandler — fired when the main frame finishes loading.
    void OnLoadEnd(CefRefPtr<CefBrowser> browser,
                   CefRefPtr<CefFrame> frame,
                   int httpStatusCode) override;

    // Returns nullptr if no bitmap has arrived yet.
    const std::uint8_t* latest_bitmap(int* out_width, int* out_height) const;

    CefRefPtr<CefBrowser> browser() const { return browser_; }

    // Event-handler injection. cef_lifecycle::set_event_handler routes
    // the host-supplied callback through here. Invoked on the main
    // thread (single-threaded message-loop mode), so no synchronisation
    // is required.
    void set_event_handler(std::function<void(const std::string&)> handler);

    // Load-end handler injection. cef_lifecycle::set_load_end_handler
    // routes here. Fired once when the main frame finishes loading
    // hello.html; panels use this to invalidate their snapshot caches
    // so the first state-push lands AFTER the page is ready.
    void set_load_end_handler(std::function<void()> handler);

private:
    int view_width_;
    int view_height_;

    std::vector<std::uint8_t> bitmap_;
    int bitmap_width_  = 0;
    int bitmap_height_ = 0;
    bool ready_ = false;

    CefRefPtr<CefBrowser> browser_;

    std::function<void(const std::string&)> event_handler_;
    std::function<void()> load_end_handler_;

    // Device-pixel ratio reported via GetScreenInfo. Default 1.0
    // (logical pixels = device pixels); set to >1.0 on Retina so
    // CEF renders at full device resolution.
    float device_scale_factor_ = 1.0f;

    IMPLEMENT_REFCOUNTING(DauntlessCefClient);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefClient);
};

}  // namespace dauntless::ui_cef
