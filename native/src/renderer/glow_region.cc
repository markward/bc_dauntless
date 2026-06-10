// native/src/renderer/glow_region.cc
#include "renderer/glow_region.h"

#include <limits>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>

namespace renderer {

GlowRegion compute_capsule_region(const assets::Model& model,
                                  const glm::vec3& center,
                                  const glm::vec3& axis,
                                  float radius) {
    GlowRegion reg;
    reg.center = center;
    reg.axis   = axis;
    reg.radius = radius * kGlowCapsuleRadiusWiden;
    reg.active = true;

    const float lat2 = reg.radius * reg.radius;
    float lo = std::numeric_limits<float>::max();
    float hi = std::numeric_limits<float>::lowest();
    int captured = 0;

    if (!model.nodes.empty()) {
        // Walk node hierarchy to chain local_transform from root down. The asset
        // pipeline orders nodes so parents precede children, so a single linear
        // pass produces correct world-per-node matrices.
        std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
        node_world[model.root_node] =
            model.nodes[model.root_node].local_transform;
        for (std::size_t i = 0; i < model.nodes.size(); ++i) {
            const auto& node = model.nodes[i];
            if (node.parent_index >= 0) {
                node_world[i] =
                    node_world[node.parent_index] * node.local_transform;
            }
            for (int mesh_idx : node.meshes) {
                if (mesh_idx < 0 ||
                    mesh_idx >= static_cast<int>(model.meshes.size())) continue;
                const auto& cpu = model.meshes[mesh_idx].cpu_data();
                if (!cpu) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 p =
                        glm::vec3(node_world[i] * glm::vec4(v.position, 1.0f));
                    const glm::vec3 d = p - center;
                    const float t = glm::dot(d, axis);            // axial proj
                    const glm::vec3 perp = d - t * axis;          // lateral
                    if (glm::dot(perp, perp) > lat2) continue;    // outside tube
                    lo = (t < lo) ? t : lo;
                    hi = (t > hi) ? t : hi;
                    ++captured;
                }
            }
        }
    }

    if (captured < kGlowCapsuleMinCaptured) {
        const float half = kGlowCapsuleFallbackHalfLenFactor * reg.radius;
        reg.aft  = -half;
        reg.fore =  half;
        return reg;
    }
    reg.aft  = lo;
    reg.fore = hi;
    return reg;
}

}  // namespace renderer
