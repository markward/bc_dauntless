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

void DauntlessCefClient::OnPaint(CefRefPtr<CefBrowser> /*browser*/,
                                  PaintElementType type,
                                  const RectList& /*dirtyRects*/,
                                  const void* buffer,
                                  int width, int height) {
    if (type != PET_VIEW) return;
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
    browser_ = browser;
}

void DauntlessCefClient::OnBeforeClose(CefRefPtr<CefBrowser> /*browser*/) {
    browser_ = nullptr;
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

}  // namespace dauntless::ui_cef
