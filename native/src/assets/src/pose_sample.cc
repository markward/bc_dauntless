// native/src/assets/src/pose_sample.cc
#include <assets/pose_sample.h>

#include <vector>

#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace assets {
namespace {

// Find the pair of keys surrounding `t` and the [0,1] fraction between them.
// Mirrors the original renderer::pose_sampler bracket() exactly.
template <typename Key>
void bracket(const std::vector<Key>& keys, float t, int& i0, int& i1,
             float& f) {
    if (keys.empty()) { i0 = i1 = -1; f = 0.0f; return; }
    if (t <= keys.front().time) { i0 = i1 = 0; f = 0.0f; return; }
    if (t >= keys.back().time) {
        i0 = i1 = static_cast<int>(keys.size()) - 1; f = 0.0f; return;
    }
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

}  // namespace

glm::vec3 sample_track_translation(const AnimationClip::NodeTrack& tr, float t,
                                   const glm::vec3& fallback) {
    if (tr.translation.empty()) return fallback;
    int a, b; float f; bracket(tr.translation, t, a, b, f);
    return glm::mix(tr.translation[a].value, tr.translation[b].value, f);
}

glm::quat sample_track_rotation(const AnimationClip::NodeTrack& tr, float t,
                                const glm::quat& fallback) {
    if (tr.rotation.empty()) return fallback;
    int a, b; float f; bracket(tr.rotation, t, a, b, f);
    return glm::normalize(glm::slerp(tr.rotation[a].value,
                                     tr.rotation[b].value, f));
}

float sample_track_scale(const AnimationClip::NodeTrack& tr, float t,
                         float fallback) {
    if (tr.scale.empty()) return fallback;
    int a, b; float f; bracket(tr.scale, t, a, b, f);
    return glm::mix(tr.scale[a].value, tr.scale[b].value, f);
}

glm::mat4 sample_track_trs(const AnimationClip::NodeTrack& tr, float t,
                           const glm::vec3& fallback_translation,
                           const glm::quat& fallback_rotation,
                           float fallback_scale) {
    const glm::vec3 trans = sample_track_translation(tr, t, fallback_translation);
    const glm::quat rot   = sample_track_rotation(tr, t, fallback_rotation);
    const float     scl   = sample_track_scale(tr, t, fallback_scale);
    return glm::translate(glm::mat4(1.0f), trans)
         * glm::mat4_cast(rot)
         * glm::scale(glm::mat4(1.0f), glm::vec3(scl));
}

}  // namespace assets
