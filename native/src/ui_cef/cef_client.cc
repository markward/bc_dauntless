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
    ready_ = true;
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
                                           cef_log_severity_t level,
                                           const CefString& message,
                                           const CefString& source,
                                           int line) {
    const std::string msg = message.ToString();
    const size_t plen = std::strlen(kEventPrefix);
    if (msg.size() < plen || msg.compare(0, plen, kEventPrefix) != 0) {
        // Not one of our event messages: a real panel console.log/warn/error.
        // We must PRINT IT OURSELVES rather than return false and let CEF log
        // it. CefSettings.log_severity is LOGSEVERITY_FATAL (cef_lifecycle.cc)
        // to stop Chromium's internal GCM/network chatter, and that setting
        // would take panel console output down with it -- silently removing
        // the primary way we debug CEF panels. Owning the print keeps panel
        // logging while Chromium's internals stay quiet.
        const char* tag = "log";
        switch (level) {
            case LOGSEVERITY_WARNING: tag = "warn";  break;
            case LOGSEVERITY_ERROR:   tag = "error"; break;
            case LOGSEVERITY_FATAL:   tag = "fatal"; break;
            default: break;
        }
        std::printf("[cef-console:%s] %s (%s:%d)\n", tag, msg.c_str(),
                    source.ToString().c_str(), line);
        std::fflush(stdout);
        return true;   // handled — do not also route it through CEF's logger
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

void DauntlessCefClient::OnLoadStart(CefRefPtr<CefBrowser> browser,
                                     CefRefPtr<CefFrame> frame,
                                     TransitionType /*transition_type*/) {
    // Same DevTools-shares-this-client guard as OnLoadEnd: opening DevTools
    // must not close the JS gate on the still-loaded overlay.
    if (browser_ && !browser->IsSame(browser_)) return;
    // Re-arm the gate for a reload (Cmd+R): between here and OnLoadEnd the
    // document is being torn down and re-parsed, so its functions are gone
    // again and pushes must not run.
    if (frame && frame->IsMain()) page_loaded_ = false;
}

void DauntlessCefClient::OnLoadEnd(CefRefPtr<CefBrowser> browser,
                                   CefRefPtr<CefFrame> frame,
                                   int /*httpStatusCode*/) {
    // The DevTools page shares this client and loads its own main frame. Its
    // load is not our page's load: firing load_end_handler_ for it would make
    // the host treat the overlay as freshly reloaded (dropping every panel
    // snapshot cache and re-pushing the dev flag) on every F12.
    if (browser_ && !browser->IsSame(browser_)) return;
    if (frame && frame->IsMain()) {
        // Open the gate BEFORE the handler runs: load_end_handler_ itself
        // pushes JS (the dev flag), and that push must not be dropped.
        page_loaded_ = true;
        if (load_end_handler_) load_end_handler_();
    }
}

}  // namespace dauntless::ui_cef
