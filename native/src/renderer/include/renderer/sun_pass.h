// native/src/renderer/include/renderer/sun_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <glm/glm.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Where a celestial body is actually drawn, and by how much its radius was
/// scaled to get there. `scale == 1` means "drawn exactly where it is".
struct VirtualPlacement {
    glm::vec3 position{0.0f};
    float     scale = 1.0f;
    bool      valid = false;   ///< false when the body is on top of the eye
};

/// Resolve the draw position of a celestial body.
///
/// A body whose true distance is INSIDE the far plane is drawn at its true
/// position with its true radius — it is real geometry and must occlude, and
/// be occluded by, everything else in the system. Only a body that genuinely
/// exceeds the far plane is remapped along the camera-to-body ray to sit just
/// inside it, with its radius scaled by the same factor so the angular size is
/// preserved.
///
/// The conditional is load-bearing at the celestial layer's scale: standing in
/// Ona 1 the star is 34,097 GU away and Ona 3 is 96,211 GU away on the far
/// side of the system. Remapping unconditionally would draw the star at
/// far*0.95 = 475,000 GU — behind the planet it occludes.
///
/// Shared with LensFlarePass so the flare projects from exactly the screen
/// position the sun disc was drawn at, and the depth-occlusion sample lands
/// on it. Two copies of this arithmetic would be two chances to drift.
VirtualPlacement solve_virtual_placement(const glm::vec3& world_pos,
                                         const glm::vec3& camera_eye,
                                         float camera_far);

class SunPass {
public:
    SunPass() = default;
    ~SunPass();
    SunPass(const SunPass&) = delete;
    SunPass& operator=(const SunPass&) = delete;

    void render(const std::vector<SunDescriptor>& suns,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                double now_seconds);

private:
    std::unordered_map<int, std::unique_ptr<assets::Mesh>>           sphere_cache_;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    assets::Mesh*    ensure_sphere(int target_tris = 256);
    assets::Texture* ensure_texture(const std::string& path);

    // Lazily-created unit-quad mesh for the flare-overlay billboard.
    // Layout: 4 vec2 corners ((-1,-1),(1,-1),(-1,1),(1,1)), drawn as a
    // GL_TRIANGLE_STRIP. The shader expands corners to world-space using
    // the camera view matrix and a uniform world center + half-size.
    std::uint32_t flare_quad_vao_ = 0;
    std::uint32_t flare_quad_vbo_ = 0;
    void ensure_flare_quad();
};

}  // namespace renderer
