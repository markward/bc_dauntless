// native/src/ui_cef/cef_client.cc
#include "cef_client.h"

#include <cstdio>
#include <cstring>

namespace dauntless::ui_cef {

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

const std::uint8_t* DauntlessCefClient::latest_bitmap(int* out_width,
                                                       int* out_height) const {
    if (!ready_) return nullptr;
    *out_width  = bitmap_width_;
    *out_height = bitmap_height_;
    return bitmap_.data();
}

}  // namespace dauntless::ui_cef
