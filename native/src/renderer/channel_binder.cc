// native/src/renderer/channel_binder.cc
#include "renderer/channel_binder.h"

#include <algorithm>
#include <cmath>

#include <glm/gtc/matrix_transform.hpp>
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
    const assets::Skeleton& skel = model.skeleton;
    const std::size_t n = skel.bones.size();
    std::vector<glm::mat4> locals(n);
    bool any_live = false;   // anything still animating or blending?

    for (std::size_t i = 0; i < n; ++i) {
        // Base local: the instance placement pose, else the bind local.
        const glm::mat4& inst_base =
            (inst.anim.has_rest && i < inst.anim.rest_locals.size())
                ? inst.anim.rest_locals[i]
                : skel.bones[i].local_transform;

        scenegraph::Instance::BoneChannel* ch =
            i < inst.anim.channels.size() ? &inst.anim.channels[i] : nullptr;
        if (!ch || ch->clip_index < 0 ||
            ch->clip_index >= static_cast<int>(model.animations.size())) {
            locals[i] = inst_base;
            continue;
        }
        const assets::AnimationClip& clip = model.animations[ch->clip_index];
        if (ch->track_index < 0 ||
            ch->track_index >= static_cast<int>(clip.tracks.size())) {
            locals[i] = inst_base;
            continue;
        }
        const assets::AnimationClip::NodeTrack& tr =
            clip.tracks[ch->track_index];

        // Omitted-channel base: walks/generic clips fall back to the CLIP's
        // own rest pose (matching the historical non-layered sample_pose);
        // gestures/idles fall back to the instance placement.
        glm::mat4 base = inst_base;
        if (ch->use_clip_base) {
            auto rit = clip.rest_locals.find(skel.bones[i].name);
            base = rit != clip.rest_locals.end()
                       ? rit->second
                       : skel.bones[i].local_transform;
        }
        glm::vec3 base_t; glm::quat base_r; float base_s;
        decompose_trs(base, base_t, base_r, base_s);

        // Playback time: hold_at_start pins t=0; loop wraps; else clamp+hold.
        const float dur = clip.duration_seconds;
        double elapsed = now_wall_time - ch->start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;
        float t;
        if (ch->hold_at_start) {
            t = 0.0f;
            ch->settled = true;
        } else if (ch->loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= dur) {
            t = dur;
        } else {
            t = static_cast<float>(elapsed);
        }

        glm::vec3 s_t = assets::sample_track_translation(tr, t, base_t);
        glm::quat s_r = assets::sample_track_rotation(tr, t, base_r);
        float     s_s = assets::sample_track_scale(tr, t, base_s);

        // BC's gesture root-anchor: keep the clip's root ROTATION but take the
        // root POSITION from the base unless this bind carries root motion.
        if (static_cast<int>(i) == skel.root_bone_index && !ch->root_motion)
            s_t = base_t;

        // Blend window: ramp the bind-time seed toward the sampled value.
        bool blending = false;
        if (ch->blend_in_s > 0.0f && elapsed < ch->blend_in_s) {
            blending = true;
            float w = static_cast<float>(elapsed) / ch->blend_in_s;
            if (blend_params().curve == 1) w = w * w * (3.0f - 2.0f * w);
            s_t = glm::mix(ch->seed_t, s_t, w);
            s_r = glm::slerp(ch->seed_r, s_r, w);
            s_s = glm::mix(ch->seed_s, s_s, w);
        }

        locals[i] = glm::translate(glm::mat4(1.0f), s_t) *
                    glm::mat4_cast(s_r) *
                    glm::scale(glm::mat4(1.0f), glm::vec3(s_s));

        // Settle bookkeeping: a channel is done when it neither advances nor
        // blends. hold_at_start settled above; loops never settle.
        if (!ch->hold_at_start && !ch->loop)
            ch->settled = (elapsed >= dur) && !blending;
        if (!ch->settled) any_live = true;
    }

    inst.anim.last_locals = locals;
    inst.anim.dirty = any_live;
    return locals;
}

}  // namespace renderer
