// native/src/renderer/include/renderer/sun_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

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
