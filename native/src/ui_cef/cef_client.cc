// native/src/ui_cef/cef_client.cc
#include "cef_client.h"

#include <cstdio>
#include <cstring>
#include <string>

namespace dauntless::ui_cef {

namespace {

// All events follow the shape `dauntless-event:<name>`. Anything not
// starting with this prefix is a normal console message and is left
// untouched.
constexpr const char kEventPrefix[] = "dauntless-event:";

}  // namespace

DauntlessCefClient::DauntlessCefClient(int view_width, int view_height)
    : view_width_(view_width), view_height_(view_height) {}

void DauntlessCefClient::GetViewRect(CefRefPtr<CefBrowser> /*browser*/,
                                      CefRect& rect) {
    rect = CefRect(0, 0, view_width_, view_height_);
}

bool DauntlessCefClient::GetScreenInfo(CefRefPtr<CefBrowser> /*browser*/,
                                        CefScreenInfo& info) {
    // Report the device-pixel ratio so CEF renders fonts/graphics at
    // device resolution rather than at logical resolution that would
    // need bilinear upscaling. Layout (HTML/CSS) still uses the
    // logical view rect — only the rasterisation density changes.
    info.device_scale_factor = device_scale_factor_;
    info.rect = CefRect(0, 0, view_width_, view_height_);
    info.available_rect = info.rect;
    return true;
}

void DauntlessCefClient::OnPaint(CefRefPtr<CefBrowser> browser,
                                  PaintElementType type,
                                  const RectList& /*dirtyRects*/,
                                  const void* buffer,
                                  int width, int height) {
    if (type != PET_VIEW) return;
    // Only the OSR overlay may write the bitmap the composite pass blits.
    // ShowDevTools shares this client, so a windowless DevTools browser would
    // otherwise paint its own page over the game's UI.
    if (browser_ && !browser->IsSame(browser_)) return;
    const size_t bytes = static_cast<size_t>(width) * height * 4;
    if (bitmap_.size() != bytes) bitmap_.resize(bytes);
    std::memcpy(bitmap_.data(), buffer, bytes);
    bitmap_width_  = width;
    bitmap_height_ = height;
    if (!ready_) {
        ready_ = true;
        std::printf("[cef] first OnPaint: %dx%d\n", width, height);
    }
}

void DauntlessCefClient::OnAfterCreated(CefRefPtr<CefBrowser> browser) {
    // toggle_devtools() passes THIS client to ShowDevTools, so CEF routes the
    // DevTools browser's lifespan through here too. Latch only the first
    // browser — the OSR overlay. Storing the DevTools browser instead would
    // silently redirect execute_javascript() / reload() / mouse / resize at
    // the DevTools page: every Python UI push then lands in a devtools://
    // frame as "setReticleText is not defined".
    if (!browser_) browser_ = browser;
}

void DauntlessCefClient::OnBeforeClose(CefRefPtr<CefBrowser> browser) {
    // Same reason: closing the DevTools window must not drop the handle to
    // the still-live OSR overlay (which would kill the UI until restart).
    if (browser_ && browser->IsSame(browser_)) browser_ = nullptr;
}

bool DauntlessCefClient::OnConsoleMessage(CefRefPtr<CefBrowser> /*browser*/,
                                           cef_log_severity_t /*level*/,
                                           const CefString& message,
                                           const CefString& /*source*/,
                                           int /*line*/) {
    const std::string msg = message.ToString();
    const size_t plen = std::strlen(kEventPrefix);
    if (msg.size() < plen || msg.compare(0, plen, kEventPrefix) != 0) {
        return false;  // not ours — let CEF log normally
    }
    if (event_handler_) {
        event_handler_(msg.substr(plen));
    }
    return true;  // suppress the default console output
}

const std::uint8_t* DauntlessCefClient::latest_bitmap(int* out_width,
                                                       int* out_height) const {
    if (!ready_) return nullptr;
    *out_width  = bitmap_width_;
    *out_height = bitmap_height_;
    return bitmap_.data();
}

void DauntlessCefClient::set_event_handler(
        std::function<void(const std::string&)> handler) {
    event_handler_ = std::move(handler);
}

void DauntlessCefClient::set_load_end_handler(std::function<void()> handler) {
    load_end_handler_ = std::move(handler);
}

void DauntlessCefClient::OnLoadEnd(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int /*httpStatusCode*/) {
    // The DevTools page shares this client and loads its own main frame. Its
    // load is not our page's load: firing load_end_handler_ for it would make
    // the host treat the overlay as freshly reloaded (dropping every panel
    // snapshot cache and re-pushing the dev flag) on every F12.
    if (browser_ && !browser->IsSame(browser_)) return;
    if (frame && frame->IsMain() && load_end_handler_) {
        load_end_handler_();
    }
}

}  // namespace dauntless::ui_cef
