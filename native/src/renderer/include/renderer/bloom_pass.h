#pragma once
#include <cstdint>
#include <memory>
#include <vector>
namespace renderer {

class Shader;

class BloomPass {
public:
    BloomPass();
    ~BloomPass();
    BloomPass(const BloomPass&) = delete;
    BloomPass& operator=(const BloomPass&) = delete;
    /// Compute bloom from hdr_color_tex; returns the bloom color texture
    /// (half-res mip0). Rebuilds the mip chain if fw/fh changed.
    std::uint32_t render(std::uint32_t hdr_color_tex, int fw, int fh);
    void set_threshold(float t) { threshold_ = t; }
private:
    struct Mip { std::uint32_t fbo = 0, tex = 0; int w = 0, h = 0; };
    void rebuild(int fw, int fh);
    void destroy();
    void draw_quad();   // binds vao_, glDrawArrays(GL_TRIANGLES,0,3)
    std::vector<Mip> mips_;
    int fw_ = 0, fh_ = 0;
    std::uint32_t vao_ = 0, vbo_ = 0;
    std::unique_ptr<Shader> prefilter_, down_, up_;
    float threshold_ = 0.8f;   // TEMP tuning — let lights (~1.0) feed bloom
};
}  // namespace renderer
