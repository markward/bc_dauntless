// native/src/ui_cef/cef_client.h
//
// CefClient + CefRenderHandler. CEF calls OnPaint each time the browser
// produces a new bitmap; we cache it for the next composite. CEF runs in
// single-threaded message-loop mode (see cef_lifecycle.cc), so OnPaint
// arrives on the main thread between pump() and composite() — no mutex.

#pragma once

#include "include/cef_client.h"
#include "include/cef_render_handler.h"

#include <cstdint>
#include <vector>

namespace dauntless::ui_cef {

class DauntlessCefClient : public CefClient,
                           public CefRenderHandler,
                           public CefLifeSpanHandler {
public:
    DauntlessCefClient(int view_width, int view_height);

    // CefClient
    CefRefPtr<CefRenderHandler>   GetRenderHandler()   override { return this; }
    CefRefPtr<CefLifeSpanHandler> GetLifeSpanHandler() override { return this; }

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

    // Returns nullptr if no bitmap has arrived yet.
    const std::uint8_t* latest_bitmap(int* out_width, int* out_height) const;

    CefRefPtr<CefBrowser> browser() const { return browser_; }

private:
    int view_width_;
    int view_height_;

    std::vector<std::uint8_t> bitmap_;
    int bitmap_width_  = 0;
    int bitmap_height_ = 0;
    bool ready_ = false;

    CefRefPtr<CefBrowser> browser_;

    IMPLEMENT_REFCOUNTING(DauntlessCefClient);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefClient);
};

}  // namespace dauntless::ui_cef
