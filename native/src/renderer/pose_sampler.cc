// native/src/renderer/pose_sampler.cc
#include "renderer/pose_sampler.h"
#include <algorithm>
#include <string>
#include <unordered_map>

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
        auto it = by_name.find(bone.name);
        if (it == by_name.end()) { out[i] = bone.local_transform; continue; }
        // Decompose the bind local for fallback components the track omits:
        // translation falls back to the bind translation, rotation to identity,
        // scale to 1. (Shared per-track interpolation lives in assets so the
        // static node-pose path uses identical math.)
        const glm::vec3 bind_t = glm::vec3(bone.local_transform[3]);
        out[i] = assets::sample_track_trs(*it->second, t, bind_t,
                                          glm::quat(1, 0, 0, 0), 1.0f);
    }
    return out;
}

}  // namespace renderer
