// native/src/renderer/channel_binder.cc
#include "renderer/channel_binder.h"

#include <algorithm>
#include <cmath>

#include <glm/gtx/quaternion.hpp>

#include <assets/model.h>
#include <assets/pose_sample.h>
#include "renderer/pose_sampler.h"

namespace {

renderer::BlendParams g_blend_params{};

// Decompose a local TRS matrix (same normalization as the historical
// pose_bone): translation from column 3, uniform scale from column lengths,
// rotation from the normalized 3x3.
void decompose_trs(const glm::mat4& m, glm::vec3& out_t, glm::quat& out_r,
                   float& out_s) {
    out_t = glm::vec3(m[3]);
    glm::mat3 m3(m);
    float s = glm::length(m3[0]);
    if (s > 1e-8f) {
        m3[0] /= s;
        m3[1] /= glm::max(glm::length(m3[1]), 1e-8f);
        m3[2] /= glm::max(glm::length(m3[2]), 1e-8f);
    } else {
        s = 1.0f;
    }
    out_r = glm::quat_cast(m3);
    out_s = s;
}

// The bone's current local for blend seeding: last evaluated pose if the
// instance has one, else its rest local, else the skeleton bind local.
glm::mat4 current_local(const scenegraph::Instance& inst,
                        const assets::Skeleton& skeleton, std::size_t bone) {
    if (bone < inst.anim.last_locals.size()) return inst.anim.last_locals[bone];
    if (inst.anim.has_rest && bone < inst.anim.rest_locals.size())
        return inst.anim.rest_locals[bone];
    return skeleton.bones[bone].local_transform;
}

}  // namespace

namespace renderer {

BlendParams blend_params() { return g_blend_params; }
void set_blend_params(const BlendParams& p) { g_blend_params = p; }

float blend_in_seconds(float clip_duration_s) {
    const BlendParams& p = g_blend_params;
    if (clip_duration_s > 0.0f && clip_duration_s < p.cap_s)
        return clip_duration_s * p.short_factor;
    return p.cap_s;
}

int bind_clip(scenegraph::Instance& inst, const assets::Model& model,
              int clip_index, const BindOptions& opts, double now_wall_time) {
    const assets::Skeleton& skel = model.skeleton;
    if (clip_index < 0 ||
        clip_index >= static_cast<int>(model.animations.size()) ||
        skel.bones.empty())
        return 0;
    const assets::AnimationClip& clip = model.animations[clip_index];

    // The strcmp join: bone index per matched track, computed BEFORE any
    // mutation so a zero-match clip changes nothing at all.
    std::vector<std::pair<std::size_t, int>> hits;  // (bone, track)
    for (int ti = 0; ti < static_cast<int>(clip.tracks.size()); ++ti)
        for (std::size_t bi = 0; bi < skel.bones.size(); ++bi)
            if (skel.bones[bi].name == clip.tracks[ti].target_node_name)
                hits.emplace_back(bi, ti);
    if (hits.empty()) return 0;

    if (inst.anim.channels.size() != skel.bones.size())
        inst.anim.channels.assign(skel.bones.size(),
                                  scenegraph::Instance::BoneChannel{});

    const float blend = opts.blend ? blend_in_seconds(clip.duration_seconds)
                                   : 0.0f;
    for (auto [bi, ti] : hits) {
        scenegraph::Instance::BoneChannel& ch = inst.anim.channels[bi];
        decompose_trs(current_local(inst, skel, bi),
                      ch.seed_t, ch.seed_r, ch.seed_s);
        ch.clip_index = clip_index;
        ch.track_index = ti;
        ch.start_wall_time = now_wall_time;
        ch.blend_in_s = blend;
        ch.loop = opts.loop;
        ch.root_motion = opts.root_motion;
        ch.use_clip_base = opts.use_clip_base;
        ch.hold_at_start = opts.hold_at_start;
        ch.settled = false;
    }
    inst.anim.dirty = true;
    return static_cast<int>(hits.size());
}

void clear_channels(scenegraph::Instance& inst) {
    for (auto& ch : inst.anim.channels)
        ch = scenegraph::Instance::BoneChannel{};
    inst.anim.dirty = true;
}

void set_rest_pose(scenegraph::Instance& inst, const assets::Model& model,
                   int clip_index, bool at_start) {
    if (clip_index < 0 ||
        clip_index >= static_cast<int>(model.animations.size()))
        return;
    const assets::AnimationClip& clip = model.animations[clip_index];
    const float t = at_start ? 0.0f : clip.duration_seconds;
    inst.anim.rest_locals = sample_pose(clip, model.skeleton, t);
    inst.anim.has_rest = true;
    if (inst.anim.channels.size() != model.skeleton.bones.size())
        inst.anim.channels.assign(model.skeleton.bones.size(),
                                  scenegraph::Instance::BoneChannel{});
    clear_channels(inst);
}

std::vector<glm::mat4> eval_channels(scenegraph::Instance& inst,
                                     const assets::Model& model,
                                     double now_wall_time) {
    (void)now_wall_time;
    // Implemented in Task 2.
    return std::vector<glm::mat4>(model.skeleton.bones.size(), glm::mat4(1.0f));
}

}  // namespace renderer
