// native/src/renderer/cube_mesh.cc
#include "cube_mesh.h"

#include <glm/glm.hpp>

namespace renderer {

assets::MeshCpu build_unit_cube() {
    // 6 faces, each with 4 vertices; positions in [-0.5, 0.5].
    // Layout: {position, normal, uv, color=white, bone_indices=0, bone_weights=0}
    struct FaceDef { glm::vec3 n; glm::vec3 p[4]; glm::vec2 uv[4]; };
    const FaceDef faces[6] = {
        // +X
        {{ 1,0,0}, {{ .5f,-.5f,-.5f},{ .5f,.5f,-.5f},{ .5f,.5f,.5f},{ .5f,-.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -X
        {{-1,0,0}, {{-.5f,-.5f,.5f},{-.5f,.5f,.5f},{-.5f,.5f,-.5f},{-.5f,-.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // +Y
        {{0, 1,0}, {{-.5f,.5f,-.5f},{-.5f,.5f,.5f},{ .5f,.5f,.5f},{ .5f,.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -Y
        {{0,-1,0}, {{-.5f,-.5f,.5f},{-.5f,-.5f,-.5f},{ .5f,-.5f,-.5f},{ .5f,-.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // +Z
        {{0,0, 1}, {{-.5f,-.5f,.5f},{ .5f,-.5f,.5f},{ .5f,.5f,.5f},{-.5f,.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -Z
        {{0,0,-1}, {{ .5f,-.5f,-.5f},{-.5f,-.5f,-.5f},{-.5f,.5f,-.5f},{ .5f,.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
    };

    assets::MeshCpu cpu;
    cpu.vertices.reserve(24);
    cpu.indices.reserve(36);

    for (const auto& f : faces) {
        const std::uint32_t base = static_cast<std::uint32_t>(cpu.vertices.size());
        for (int v = 0; v < 4; ++v) {
            assets::MeshCpu::Vertex vert{};
            vert.position = f.p[v];
            vert.normal   = f.n;
            vert.uv       = f.uv[v];
            vert.color    = glm::u8vec4(255, 255, 255, 255);
            cpu.vertices.push_back(vert);
        }
        // Two triangles per face (CCW winding when viewed from outside).
        cpu.indices.insert(cpu.indices.end(),
            {base, base+1, base+2, base, base+2, base+3});
    }
    return cpu;
}

} // namespace renderer
