// native/src/renderer/include/renderer/torpedo_sprites.h
//
// The CPU half of the instanced torpedo pass: every textured quad of every
// torpedo-family projectile, grouped by texture, so TorpedoPass draws each
// group with ONE instanced call instead of one draw (and six uniform
// uploads) per quad -- 11 per photon, ~26,000 a frame at 2,350 torpedoes.
//
// The quads are exactly the layers the old per-quad loop drew (two glow
// quads, the flare star, the core; same skips, same values, same order
// within a texture -- torpedo_sprites_test.cc holds that loop as the
// reference). Additive blending with depth writes off makes the draw order
// across textures irrelevant to the picture. Torpedoes whose quads lie
// wholly outside the view frustum are dropped. Disruptors are not sprites.
#pragma once

#include <renderer/frame.h>

#include <glm/glm.hpp>

#include <string>
#include <vector>

namespace renderer {

/// One quad, laid out as the instance attributes torpedo.vert reads.
struct TorpedoSprite {
    glm::vec4 centre_size;   // xyz world centre, w half-size (world units)
    glm::vec4 axis_x_alpha;  // xyz quad x half-axis direction, w alpha multiplier
    glm::vec4 axis_y;        // xyz quad y half-axis direction, w unused
    glm::vec4 tint;
};
static_assert(sizeof(TorpedoSprite) == 64, "instance stride is 4 x vec4");

struct TorpedoSpriteBatch {
    std::string texture;
    std::vector<TorpedoSprite> sprites;
};

/// Fill `batches` with this frame's quads. Batches are reused across calls
/// (their sprite storage keeps its capacity): every batch's sprites are
/// cleared first, and a texture seen for the first time appends a batch, so
/// a batch may be empty this frame. `cam_up_world` seeds the spinning root
/// frame exactly as the old loop did; `view_proj` is only used to cull.
void build_torpedo_sprites(const std::vector<TorpedoDescriptor>& torpedoes,
                           const glm::vec3& cam_pos,
                           const glm::vec3& cam_up_world,
                           const glm::mat4& view_proj,
                           std::vector<TorpedoSpriteBatch>& batches);

}  // namespace renderer
