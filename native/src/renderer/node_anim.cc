#include "renderer/node_anim.h"
#include <algorithm>
#include <string>
#include <unordered_map>
#include <glm/gtx/quaternion.hpp>
#include <assets/model.h>
#include <assets/animation.h>
#include <assets/pose_sample.h>

namespace renderer {

int resolve_overridden_node(
    const assets::Model& model, const std::string& name,
    const std::unordered_map<int, glm::mat4>& overrides) {
    int first = -1;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name != name) continue;
        if (first < 0) first = static_cast<int>(i);
        // Prefer the duplicate that actually carries an override — that is the
        // node the clip animates (and whose mesh subtree rotates). This keeps a
        // coupling's anim/rest reads on the same rotating node.
        if (overrides.count(static_cast<int>(i)))
            return static_cast<int>(i);
    }
    return first;
}

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

namespace {

// Split a TRS matrix into translation / rotation / uniform scale, so a track
// that OMITS a channel can fall back to that channel of the base pose.
void decompose_trs(const glm::mat4& m, glm::vec3& t, glm::quat& r, float& s) {
    t = glm::vec3(m[3]);
    glm::mat3 m3(m);
    s = glm::length(m3[0]);
    if (s > 1e-8f) {
        m3[0] /= s;
        m3[1] /= glm::max(glm::length(m3[1]), 1e-8f);
        m3[2] /= glm::max(glm::length(m3[2]), 1e-8f);
    } else {
        s = 1.0f;
    }
    r = glm::quat_cast(m3);
}

}  // namespace

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
        const glm::mat4& model_local = model.nodes[it->second].local_transform;

        // RETARGET the clip's motion onto the model's node. An EXTERNAL clip NIF
        // (the lift doors: data/animations/DB_door_L1.nif) keys its nodes in ITS
        // OWN root frame, while in the bridge model those nodes hang under a
        // parent that already carries their placement. Writing the clip's key
        // straight in as the node's LOCAL transform applies the placement twice
        // (the door teleports out of the doorway by exactly its own rest vector).
        // So take the clip's motion as a DELTA against the clip's OWN rest pose
        // and apply it in the model node's frame:
        //
        //     override = model_local * inverse(clip_rest) * clip_sampled
        //
        // At t=0 the sampled pose IS the clip's rest -> delta = identity -> the
        // node sits exactly at its model rest. For the bridge's EMBEDDED clip the
        // clip rest EQUALS the model local, so this collapses to the sampled pose
        // (unchanged). For a rotation-only clip (the chairs) the delta is a pure
        // rotation about the node's own origin, so the seat turns without moving.
        auto rit = clip.rest_locals.find(tr.target_node_name);
        const bool have_rest = rit != clip.rest_locals.end();
        // Sample in the CLIP's frame: channels the track omits must fall back to
        // the CLIP's rest, not the model's, or the delta mixes two frames.
        const glm::mat4& base = have_rest ? rit->second : model_local;

        glm::vec3 base_t; glm::quat base_r; float base_s;
        decompose_trs(base, base_t, base_r, base_s);
        const glm::mat4 sampled =
            assets::sample_track_trs(tr, t, base_t, base_r, base_s);

        overrides[it->second] =
            have_rest ? model_local * glm::inverse(base) * sampled
                      : sampled;   // no rest recorded: legacy in-model sampling
    }
    return overrides;
}

}  // namespace renderer
