// native/src/renderer/include/renderer/planet_detail_uniforms.h
#pragma once

#include <array>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include "renderer/planet_clipmap_schedule.h"
#include "renderer/planet_detail_noise.h"

// The per-draw uniform block of the planet_ program (opaque.frag compiled
// with PLANET_SURFACE; spec 2026-10-08 §5.4, §6). One struct, one `apply`, so
// every u_pd_* uniform is set in exactly one place.
namespace renderer {
class Shader;
}

namespace renderer::planet_detail {

/// An empty valid rect: no absolute texel is inside it.
inline constexpr glm::vec4 kEmptyValid{1e9f, 1e9f, -1e9f, -1e9f};

struct SampleUniforms {
    bool  enabled = false;           // u_pd_enabled
    GLuint atlas = 0;                // ClipmapAtlas::texture(), bound to unit 12
    int   levels = 0;
    float ts0 = 0.1f;                // level-0 texel, GU
    /// Absolute-texel rect per level, (x0, y0, x1, y1), right/top exclusive:
    /// the schedule's valid(L), which is the authority for baked content.
    std::array<glm::vec4, kMaxLevels> valid{kEmptyValid, kEmptyValid, kEmptyValid,
                                            kEmptyValid, kEmptyValid};
    glm::vec3 A{0, 0, 1}, E{1, 0, 0}, N{0, 1, 0};   // anchor frame, planet-local
    float R = 1.0f;                  // GU
    float scale_local = 1.0f;        // body units -> GU (instance world scale)
    int   type = 0;                  // SurfaceType
    glm::vec3 ocean{0.0f};
    bool  has_ocean = false;
    float ocean_tol = 0.15f;
    float strength = 1.0f, albedo = 1.0f, scale = 1.0f;
    TypeParams params{};
    int   debug = 0;                 // != 0: tint each level (L0..L4)
};

/// Set every u_pd_* uniform on `s` (which must be the planet_ program) and
/// bind `u.atlas` to GL_TEXTURE12, leaving GL_TEXTURE0 active. With
/// enabled == false ONLY u_pd_enabled = 0 is set and nothing is bound: the
/// shader never reads the atlas then.
void apply(Shader& s, const SampleUniforms& u);

}  // namespace renderer::planet_detail
