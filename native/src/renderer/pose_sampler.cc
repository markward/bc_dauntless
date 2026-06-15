// native/src/renderer/pose_sampler.cc
#include "renderer/pose_sampler.h"
#include <algorithm>
#include <string>
#include <unordered_map>

#include <glm/gtx/quaternion.hpp>

#include <assets/pose_sample.h>

namespace renderer {

std::vector<glm::mat4> sample_pose(const assets::AnimationClip& clip,
                                   const assets::Skeleton& skeleton,
                                   float t) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);

    std::unordered_map<std::string, const assets::AnimationClip::NodeTrack*> by_name;
    for (const auto& tr : clip.tracks) by_name[tr.target_node_name] = &tr;

    std::vector<glm::mat4> out(skeleton.bones.size());
    for (std::size_t i = 0; i < skeleton.bones.size(); ++i) {
        const auto& bone = skeleton.bones[i];

        // BASE pose for this bone: the clip's SOURCE-NIF rest local (the placed
        // standing pose) if available, else the skeleton's own bind local. BC
        // placement clips are sparse — the arms-down standing orientation lives
        // in the rest pose, NOT in keyframes — so basing the pose on the body's
        // T-pose bind and falling back to identity contorts the body. Use the
        // rest local and decompose it so each channel the track OMITS falls back
        // to the REST value (not identity).
        auto rit = clip.rest_locals.find(bone.name);
        const glm::mat4& base =
            rit != clip.rest_locals.end() ? rit->second : bone.local_transform;

        auto it = by_name.find(bone.name);
        if (it == by_name.end()) { out[i] = base; continue; }

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
        out[i] = assets::sample_track_trs(*it->second, t, base_t, base_r, base_s);
    }
    return out;
}

}  // namespace renderer
