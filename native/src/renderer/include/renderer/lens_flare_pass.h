// native/src/renderer/include/renderer/lens_flare_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

// One vertex of the per-wedge mesh: 2D position in unit-disk-local space,
// UV in [0,1]. Kept POD-like so std::vector<NgonVertex> uploads directly.
struct NgonVertex {
    float pos[2];
    float uv[2];
};

struct NgonMeshData {
    std::vector<NgonVertex>     vertices;
    std::vector<unsigned int>   indices;
};

// Pure function: build CPU-side mesh data for an N-gon disk where each
// wedge has its own (0,0)→(1,0) bottom UV and (0.5, 1.0) center UV. No GL
// state touched, so this is unit-testable without a context.
NgonMeshData build_ngon_mesh(int wedges);

class LensFlarePass {
public:
    LensFlarePass() = default;
    ~LensFlarePass();
    LensFlarePass(const LensFlarePass&)            = delete;
    LensFlarePass& operator=(const LensFlarePass&) = delete;

    void render(const std::vector<LensFlareDescriptor>& flares,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                int viewport_w, int viewport_h,
                double now_seconds);

private:
    struct WedgeMesh {
        unsigned int vao = 0;
        unsigned int vbo = 0;
        unsigned int ebo = 0;
        int          index_count = 0;
    };

    std::unordered_map<int, WedgeMesh>                                 wedge_meshes_;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>>  texture_cache_;

    WedgeMesh&       ensure_wedge_mesh(int n);
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
