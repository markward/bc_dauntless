#pragma once
#include <cstdint>
namespace renderer {
class ResolvePass {
public:
    ResolvePass();
    ~ResolvePass();
    ResolvePass(const ResolvePass&) = delete;
    ResolvePass& operator=(const ResolvePass&) = delete;
    void set_hdr_enabled(bool e) { hdr_enabled_ = e; }
    /// Draw a fullscreen triangle sampling `hdr_color_tex` into the
    /// currently-bound framebuffer. Disables depth-test + blend and
    /// restores them. Caller binds the target framebuffer + viewport first.
    void draw(std::uint32_t hdr_color_tex);
private:
    std::uint32_t program_ = 0, vao_ = 0, vbo_ = 0;
    int u_hdr_loc_ = -1, u_hdr_enabled_loc_ = -1;
    bool hdr_enabled_ = true;
};
}  // namespace renderer
