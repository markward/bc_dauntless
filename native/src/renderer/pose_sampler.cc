// native/src/renderer/pose_sampler.cc
#include "renderer/pose_sampler.h"
#include <algorithm>
#include <string>
#include <unordered_map>

#include <glm/gtx/quaternion.hpp>

#include <assets/pose_sample.h>

namespace {

// Pose one bone: if `track` is null, return `base`; else sample the track with
// each omitted channel falling back to base's T/R/S.
glm::mat4 pose_bone(const assets::AnimationClip::NodeTrack* track,
                    const glm::mat4& base, float t) {
    if (!track) return base;
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
    return assets::sample_track_trs(*track, t, base_t, base_r, base_s);
}

}  // namespace

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
        out[i] = pose_bone(it == by_name.end() ? nullptr : it->second, base, t);
    }
    return out;
}

std::vector<glm::mat4> sample_pose_over_base(
    const assets::AnimationClip& clip, const assets::Skeleton& skeleton,
    float t, const std::vector<glm::mat4>& base_locals) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);
    std::unordered_map<std::string, const assets::AnimationClip::NodeTrack*> by_name;
    for (const auto& tr : clip.tracks) by_name[tr.target_node_name] = &tr;

    std::vector<glm::mat4> out(skeleton.bones.size());
    for (std::size_t i = 0; i < skeleton.bones.size(); ++i) {
        const glm::mat4 base =
            i < base_locals.size() ? base_locals[i] : skeleton.bones[i].local_transform;
        auto it = by_name.find(skeleton.bones[i].name);
        out[i] = pose_bone(it == by_name.end() ? nullptr : it->second, base, t);
        // Anchor the ROOT translation to the placement: chair-turn clips (e.g.
        // db_chair_H_face_capt) carry a Bip01 root translation that would slide
        // the officer off the station. Keep the clip's root ROTATION (the swivel
        // toward the captain) but take the root POSITION from the placement base.
        // Root-less clips (breathe, neck turns) already carry the base
        // translation here, so this is a no-op for them.
        if (static_cast<int>(i) == skeleton.root_bone_index)
            out[i][3] = base[3];
    }
    return out;
}

}  // namespace renderer
