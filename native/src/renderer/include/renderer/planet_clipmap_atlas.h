// native/src/renderer/include/renderer/planet_clipmap_atlas.h
#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include <glad/glad.h>

#include "renderer/planet_clipmap_schedule.h"
#include "renderer/planet_detail_noise.h"

// GL layer of the planet surface-detail clipmap: ONE RGBA16F sampler2D atlas
// (no texture arrays on this driver) holding every level's toroidal band
// stacked vertically — level L occupies rows [L*kBandRows, (L+1)*kBandRows),
// kLevelSize wide. `bake` turns the scheduler's BakeRects into scissored
// full-screen-triangle draws of planet_bake.frag, the GLSL twin of
// planet_detail_noise.cc. Texel = (h, dot(grad,E), dot(grad,N), a).
namespace renderer {
class Shader;
}

namespace renderer::planet_detail {

struct BakeParams {
    Anchor anchor;
    SurfaceType type;
    TypeParams params;
    float scale;
    std::uint32_t seed;
    float ts0_gu;
    std::vector<int> octaves_per_level;   // already decided per level (octaves_for_texel)
};

class ClipmapAtlas {
public:
    /// GL_RGBA16F, kLevelSize x (kBandRows*levels), LINEAR, S=REPEAT,
    /// T=CLAMP_TO_EDGE, cleared to zero. Needs a current GL context.
    explicit ClipmapAtlas(int levels);
    ~ClipmapAtlas();
    ClipmapAtlas(const ClipmapAtlas&) = delete;
    ClipmapAtlas& operator=(const ClipmapAtlas&) = delete;
    ClipmapAtlas(ClipmapAtlas&& o) noexcept;
    ClipmapAtlas& operator=(ClipmapAtlas&& o) noexcept;

    /// One scissored draw per rect. Restores the draw FBO, viewport, scissor
    /// test + box, current program, VAO, and blend/depth/cull enables.
    void bake(const std::vector<BakeRect>& rects, const BakeParams& p);

    GLuint texture() const { return tex_; }
    int levels() const { return levels_; }

private:
    void release() noexcept;

    int levels_ = 0;
    GLuint tex_ = 0;
    GLuint fbo_ = 0;
    GLuint vao_ = 0;
    std::unique_ptr<Shader> shader_;
};

}  // namespace renderer::planet_detail
