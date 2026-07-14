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

// Find the model node a clip track should DRIVE, given every node with that
// name. BC set NIFs nest a DUPLICATE: an outer node carrying the PLACEMENT and
// an identity-local CHILD of the same name holding the mesh (DBridge.nif's
// [217]/[220] 'console seat 01'; the lift doors have the same shape). BC's
// NiKeyframeController overwrites its TARGET node's local outright, and the
// clip's keys are the absolute local TRS of the PLACED node — so pick the
// candidate whose own local TRANSLATION matches the clip's rest translation.
// Translation only: the clip's rest ROTATION is exactly the quantity we cannot
// trust (see sample_node_overrides). Returns -1 when nothing matches.
int placed_node_for(const assets::Model& model, const std::string& name,
                    const glm::mat4& clip_rest) {
    const glm::vec3 want(clip_rest[3]);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name != name) continue;
        const glm::vec3 got(model.nodes[i].local_transform[3]);
        if (glm::length(got - want) < 1e-3f) return static_cast<int>(i);
    }
    return -1;
}

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

        auto rit = clip.rest_locals.find(tr.target_node_name);
        const bool have_rest = rit != clip.rest_locals.end();

        // Prefer the PLACED node (the outer duplicate whose own local carries the
        // placement) over `index_of`'s last-wins pick (the identity-local mesh
        // CHILD of the same name). BC's NiKeyframeController overwrites its
        // target's local outright, so the clip's keys ARE that placed node's
        // absolute local TRS in the set's frame — write the sampled pose in
        // DIRECTLY. Nothing is double-applied: the mesh child is identity-local.
        const int placed =
            have_rest ? placed_node_for(model, tr.target_node_name, rit->second)
                      : -1;
        const int target = placed >= 0 ? placed : it->second;
        const glm::mat4& model_local = model.nodes[target].local_transform;

        // Sample in the CLIP's frame: channels the track omits must fall back to
        // the CLIP's rest, not the model's, or the two frames get mixed.
        const glm::mat4& base = have_rest ? rit->second : model_local;

        glm::vec3 base_t; glm::quat base_r; float base_s;
        decompose_trs(base, base_t, base_r, base_s);
        const glm::mat4 sampled =
            assets::sample_track_trs(tr, t, base_t, base_r, base_s);

        // FALLBACK (no placed duplicate found): retarget the clip's motion as a
        // DELTA against its own rest, applied in the model node's frame —
        //
        //     override = model_local * inverse(clip_rest) * clip_sampled
        //
        // — because such a clip's keys are in ITS OWN root frame while the model
        // node hangs under a parent that already carries the placement; writing
        // the key straight in would apply that placement TWICE.
        //
        // This path is DELIBERATELY not the default: it consults the clip's rest
        // ROTATION, which BC does not author reliably. BC bakes each *_reverse /
        // *_in chair clip's rest to that clip's FIRST KEY, not to the set's rest
        // pose (db_chair_H_face_capt_reverse rest = Rz(-60), keys -60 -> 0), so
        // inverse(clip_rest) MIRRORS it: the chair swings OUT to +60 and holds
        // there. It only ever worked for doors by luck — a door's baked rest
        // rotation genuinely IS its placement rotation, so the term cancels.
        overrides[target] = (placed < 0 && have_rest)
                                ? model_local * glm::inverse(base) * sampled
                                : sampled;
    }
    return overrides;
}

}  // namespace renderer
