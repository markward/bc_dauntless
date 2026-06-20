#pragma once
#include <cstdint>

namespace renderer {

class ShadowMapTarget {
public:
    ShadowMapTarget() = default;
    ~ShadowMapTarget();
    ShadowMapTarget(const ShadowMapTarget&) = delete;
    ShadowMapTarget& operator=(const ShadowMapTarget&) = delete;

    void resize(int w, int h);
    void bind() const;

    std::uint32_t depth_texture() const { return depth_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t depth_tex_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
