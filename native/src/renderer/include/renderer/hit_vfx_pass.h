// native/src/renderer/include/renderer/hit_vfx_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <memory>
#include <vector>

namespace scenegraph { struct Camera; class World; }

namespace renderer {

class Pipeline;

/// Where a hit VFX sits right now, in world space.
///
/// With a hull anchor (`has_body_anchor`) and a live instance, that is
/// `instance_world * body_point`, recomputed every frame so the impact rides
/// the ship. Without one — no mesh normal, no instance, stale id — it falls
/// back to the descriptor's frozen `world_pos`.
///
/// The flash billboard used `world_pos` unconditionally while the sparks in
/// the SAME descriptor already tracked the instance matrix, so over the flash's
/// 0.7 s life it slid ~4.4 GU at combat speed while the sparks stayed put.
/// Both now go through here.
glm::vec3 hit_vfx_anchor_point(const HitVfxDescriptor& v,
                               const glm::mat4* instance_world);

class HitVfxPass {
public:
    HitVfxPass();
    ~HitVfxPass();
    HitVfxPass(const HitVfxPass&)            = delete;
    HitVfxPass& operator=(const HitVfxPass&) = delete;

    /// Render every active hit VFX as an additive billboard at its world
    /// position.  Size eases 0→1 over first 100ms; alpha fades 1→0 over
    /// next 400ms based on `age` (engine prunes after 500ms).
    void render(const std::vector<HitVfxDescriptor>& vfx,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

    /// Sprite paths this pass opens via std::ifstream, relative to the
    /// renderer's runtime CWD (the project root). Exposed so a test can
    /// verify they resolve — a missing "game/" prefix silently no-ops the
    /// whole pass.
    static const char* impact_texture_path();
    static const char* spark_texture_path();

private:
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::unique_ptr<assets::Texture> texture_;
    std::unique_ptr<assets::Texture> spark_texture_;

    void ensure_quad_mesh();
    void ensure_texture();
    void ensure_spark_texture();
};

}  // namespace renderer
