// native/src/renderer/pose_sampler.cc
#include "renderer/pose_sampler.h"
#include <algorithm>
#include <string>
#include <unordered_map>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace renderer {
namespace {

// Find the pair of keys surrounding `t` and the [0,1] fraction between them.
template <typename Key>
void bracket(const std::vector<Key>& keys, float t, int& i0, int& i1, float& f) {
    if (keys.empty()) { i0 = i1 = -1; f = 0.0f; return; }
    if (t <= keys.front().time) { i0 = i1 = 0; f = 0.0f; return; }
    if (t >= keys.back().time)  { i0 = i1 = static_cast<int>(keys.size()) - 1; f = 0.0f; return; }
    for (std::size_t k = 1; k < keys.size(); ++k) {
        if (t < keys[k].time) {
            i0 = static_cast<int>(k) - 1; i1 = static_cast<int>(k);
            const float span = keys[i1].time - keys[i0].time;
            f = span > 1e-8f ? (t - keys[i0].time) / span : 0.0f;
            return;
        }
    }
    i0 = i1 = static_cast<int>(keys.size()) - 1; f = 0.0f;
}

glm::vec3 sample_translation(const assets::AnimationClip::NodeTrack& tr, float t,
                             const glm::vec3& fallback) {
    if (tr.translation.empty()) return fallback;
    int a, b; float f; bracket(tr.translation, t, a, b, f);
    return glm::mix(tr.translation[a].value, tr.translation[b].value, f);
}
glm::quat sample_rotation(const assets::AnimationClip::NodeTrack& tr, float t,
                          const glm::quat& fallback) {
    if (tr.rotation.empty()) return fallback;
    int a, b; float f; bracket(tr.rotation, t, a, b, f);
    return glm::normalize(glm::slerp(tr.rotation[a].value, tr.rotation[b].value, f));
}
float sample_scale(const assets::AnimationClip::NodeTrack& tr, float t, float fallback) {
    if (tr.scale.empty()) return fallback;
    int a, b; float f; bracket(tr.scale, t, a, b, f);
    return glm::mix(tr.scale[a].value, tr.scale[b].value, f);
}

}  // namespace

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
        const auto& tr = *it->second;
        // Decompose the bind local for fallback components the track omits.
        const glm::vec3 bind_t = glm::vec3(bone.local_transform[3]);
        const glm::vec3 trans = sample_translation(tr, t, bind_t);
        const glm::quat rot   = sample_rotation(tr, t, glm::quat(1, 0, 0, 0));
        const float     scl   = sample_scale(tr, t, 1.0f);
        glm::mat4 m = glm::translate(glm::mat4(1.0f), trans)
                    * glm::mat4_cast(rot)
                    * glm::scale(glm::mat4(1.0f), glm::vec3(scl));
        out[i] = m;
    }
    return out;
}

}  // namespace renderer
