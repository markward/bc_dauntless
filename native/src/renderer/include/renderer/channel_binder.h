// native/src/renderer/include/renderer/channel_binder.h
//
// BC-faithful per-bone channel binder. stbc.exe's TGAnimBlender binds clip
// channels to character nodes by an exact, case-sensitive, full-string strcmp
// join of two name-sorted tables (decomp: SetTarget 0x006C6900, LoadAnimation
// 0x006C8290, lookup FUN_006CC730): hit = rebind that node's controllers to
// the clip's keys; miss = the channel is dead ballast, silently. Every bridge
// animation in BC is NON-exclusive (TGAnimAction_Create(…, 0, 0[, 1])), so
// bones a clip does not track keep whatever drove them before — per-node
// last-bind-wins. This unit reproduces that observable machine over
// scenegraph::Instance::SkeletalAnim.
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <scenegraph/instance.h>

namespace assets { struct Model; }

namespace renderer {

struct BindOptions {
    bool loop = false;           // idle loops; gestures/walks clamp+hold
    bool root_motion = false;    // root bone: APPLY the clip's translation
    bool use_clip_base = false;  // omitted-channel base = clip's rest_locals
    bool hold_at_start = false;  // evaluate at t=0 and settle immediately
    bool blend = false;          // blend-in per blend_params() (BC default ON;
                                 // positioning paths snap)
};

/// Feel dials for the blend-in. BC (TGAnimAction::Play, 0x00704140):
/// blendTime = dur < 0.34 ? dur * 0.75 : 0.34. curve: 0 = linear (default;
/// NiAnimBlender's actual ramp is undecoded), 1 = smoothstep.
struct BlendParams {
    float cap_s = 0.34f;
    float short_factor = 0.75f;
    int   curve = 0;
};
BlendParams blend_params();
void set_blend_params(const BlendParams& p);
/// BC's blend-time formula for a clip of `clip_duration_s`, per current params.
float blend_in_seconds(float clip_duration_s);

/// Bind model.animations[clip_index] onto the instance's channel table: for
/// each clip track whose target_node_name exactly equals a bone name, overwrite
/// that bone's channel (seeding blend-from from last_locals, else rest_locals,
/// else the bind local). Unmatched tracks are dropped; untracked bones keep
/// their previous channel. Returns the number of bones bound — 0 means the
/// clip is dead ballast on this skeleton and NOTHING changed (BC's silent
/// no-op; the old play_instance_gesture gate, now emergent).
int bind_clip(scenegraph::Instance& inst, const assets::Model& model,
              int clip_index, const BindOptions& opts, double now_wall_time);

/// Unbind every channel; bones fall back to rest_locals (kept) or bind.
void clear_channels(scenegraph::Instance& inst);

/// Sample the placement clip ONCE (t=0 if at_start else t=duration) into
/// rest_locals via sample_pose, set has_rest, and clear all channels. Snap —
/// no blend (BC's positioning path bypasses blending). NOTE: does NOT clear
/// last_locals, so a bind_clip issued before the next eval seeds its blend
/// from the previously evaluated pose (falling back to the new rest_locals
/// only when last_locals is empty).
void set_rest_pose(scenegraph::Instance& inst, const assets::Model& model,
                   int clip_index, bool at_start);

/// Evaluate every bone's channel at `now` into per-bone LOCAL transforms
/// (skeleton order): unbound → rest/bind local; bound → track sample at
/// fmod/clamped t over the channel's base (instance rest_locals, or the
/// clip's own rest_locals when use_clip_base), root translation from base
/// unless root_motion, then blend seed→sample while inside the blend window.
/// Side effects: updates channel settled flags, writes anim.last_locals, and
/// clears anim.dirty when nothing needs further rebuilds. Feed the result to
/// build_bone_palette.
std::vector<glm::mat4> eval_channels(scenegraph::Instance& inst,
                                     const assets::Model& model,
                                     double now_wall_time);

}  // namespace renderer
