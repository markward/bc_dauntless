// native/src/renderer/include/renderer/nebula_volumetric_pass.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct NebulaVolume;
struct Lighting;

/// Modern-VFX volumetric raymarch of the nebula fbm density field.
///
/// A single full-screen pass: for each fragment it reconstructs the world ray
/// from `inv_view_proj`, intersects the sphere-union to find the march
/// interval, clamps the far end to the scene depth (from the HDR depth
/// texture, so hulls — including the player ship — occlude the cloud), and
/// marches front-to-back accumulating single-scatter from up to 4 directional
/// lights plus the nebula self-glow.
///
/// Compositing avoids any feedback loop: the shader outputs PREMULTIPLIED
/// `vec4(lit, alpha)` and is BLENDED over the currently-bound HDR target via
/// `glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)` with depth test/write OFF. It
/// never samples the HDR colour — only the depth texture (read-only; safe
/// while not writing depth).
///
/// Full-res direct into the HDR target. Task 6 slots a half-res + temporal
/// scratch target in front of `render()` without changing the data contract.
class NebulaVolumetricPass {
public:
    NebulaVolumetricPass();
    ~NebulaVolumetricPass();
    NebulaVolumetricPass(const NebulaVolumetricPass&) = delete;
    NebulaVolumetricPass& operator=(const NebulaVolumetricPass&) = delete;

    /// Composite the volumetric cloud into the currently-bound HDR target.
    /// Early-outs (zero GL work) on empty `volumes`.
    ///
    /// `hdr_color_tex` is accepted for signature symmetry / future use but is
    /// NOT sampled (blend compositing). `hdr_depth_tex` IS sampled to clamp
    /// the march to hulls. `inv_view_proj` = inverse(proj * view); `eye` is
    /// the camera world position; `time` drives the slow density drift.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaVolume>& volumes,
                const Lighting& lighting,
                std::uint32_t hdr_color_tex,
                std::uint32_t hdr_depth_tex,
                const glm::mat4& inv_view_proj,
                const glm::vec3& eye,
                float time);

private:
    void initialize_gl();

    bool         initialized_ = false;
    unsigned int vao_ = 0;   // empty VAO; fullscreen triangle uses gl_VertexID
};

}  // namespace renderer
