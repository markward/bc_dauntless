#include "renderer/node_anim.h"
#include <algorithm>
#include <string>
#include <unordered_map>
#include <glm/gtx/quaternion.hpp>
#include <assets/model.h>
#include <assets/animation.h>
#include <assets/pose_sample.h>

namespace renderer {

std::vector<glm::mat4> compose_node_worlds(
    const assets::Model& model, const glm::mat4& instance_world,
    const std::unordered_map<int, glm::mat4>& overrides) {
    std::vector<glm::mat4> world(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return world;

    auto local_of = [&](int i) -> const glm::mat4& {
        auto it = overrides.find(i);
        return it != overrides.end() ? it->second
                                     : model.nodes[i].local_transform;
    };

    world[model.root_node] = instance_world * local_of(model.root_node);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0)
            world[i] = world[node.parent_index] * local_of(static_cast<int>(i));
    }
    return world;
}

std::unordered_map<int, glm::mat4> sample_node_overrides(
    const assets::AnimationClip& clip, const assets::Model& model, float t) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);

    // node name -> index, for matching tracks to nodes.
    std::unordered_map<std::string, int> index_of;
    index_of.reserve(model.nodes.size());
    for (std::size_t i = 0; i < model.nodes.size(); ++i)
        index_of[model.nodes[i].name] = static_cast<int>(i);

    std::unordered_map<int, glm::mat4> overrides;
    for (const auto& tr : clip.tracks) {
        auto it = index_of.find(tr.target_node_name);
        if (it == index_of.end()) continue;            // e.g. "Camera captain"
        const glm::mat4& base = model.nodes[it->second].local_transform;
        const glm::vec3 base_t = glm::vec3(base[3]);
        glm::mat3 m3(base);
        float base_s = glm::length(m3[0]);
        if (base_s > 1e-8f) {
            m3[0] /= base_s;
            m3[1] /= glm::max(glm::length(m3[1]), 1e-8f);
            m3[2] /= glm::max(glm::length(m3[2]), 1e-8f);
        } else {
            base_s = 1.0f;
        }
        const glm::quat base_r = glm::quat_cast(m3);
        overrides[it->second] =
            assets::sample_track_trs(tr, t, base_t, base_r, base_s);
    }
    return overrides;
}

}  // namespace renderer
