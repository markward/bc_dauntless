// native/src/ui_cef/cef_composite_pass.h
//
// Uploads the latest CEF OSR bitmap to a GL texture and draws it as a
// fullscreen triangle over the 3D scene with premultiplied-alpha blend.
// Saves and restores GL state (cull / depth / blend / scissor) so the
// next frame's 3D passes resume from the state they left in.

#pragma once

#include <cstdint>

namespace dauntless::ui_cef {

class CefCompositePass {
public:
    CefCompositePass();
    ~CefCompositePass();

    CefCompositePass(const CefCompositePass&) = delete;
    CefCompositePass& operator=(const CefCompositePass&) = delete;

    // pixels is BGRA8 premultiplied (CEF OSR contract). No-op if pixels==nullptr.
    void draw_fullscreen(const std::uint8_t* pixels, int width, int height);

private:
    unsigned int program_id_ = 0;
    unsigned int vao_        = 0;
    unsigned int vbo_        = 0;
    unsigned int tex_id_     = 0;
    int last_width_  = 0;
    int last_height_ = 0;
};

}  // namespace dauntless::ui_cef
