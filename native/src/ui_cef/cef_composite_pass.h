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

    // Upload and draw are separate so the host can time them as separate
    // profiler scopes, and so a frame CEF did not repaint can skip the upload
    // and redraw the texture it already holds (cef_upload_policy.h).

    // pixels is BGRA8 premultiplied (CEF OSR contract). No-op if pixels==nullptr.
    void upload(const std::uint8_t* pixels, int width, int height);
    // Draws the texture as last uploaded. No-op before the first upload.
    void draw();

    // CPU time per section of draw(), summed since the last take. The
    // sections are: program/texture/uniform setup, the glIsEnabled +
    // glGetIntegerv state save, the state set + draw call, and the restore.
    struct DrawTimings {
        double setup_ms   = 0.0;
        double query_ms   = 0.0;
        double draw_ms    = 0.0;
        double restore_ms = 0.0;
        int    draws      = 0;
    };
    DrawTimings take_draw_timings() {
        DrawTimings t = draw_timings_;
        draw_timings_ = DrawTimings{};
        return t;
    }

    bool allocated() const { return last_width_ > 0 && last_height_ > 0; }
    bool size_differs(int width, int height) const {
        return width != last_width_ || height != last_height_;
    }

private:
    unsigned int program_id_ = 0;
    unsigned int vao_        = 0;
    unsigned int vbo_        = 0;
    unsigned int tex_id_     = 0;
    int last_width_  = 0;
    int last_height_ = 0;
    DrawTimings draw_timings_;
};

}  // namespace dauntless::ui_cef
