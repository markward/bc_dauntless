// native/src/assets/include/assets/pose_sample.h
//
// Per-track keyframe interpolation, shared by:
//   * renderer::sample_pose (GPU palette skinning — pose_sampler.cc), and
//   * assets::apply_pose_to_nodes (static node-posing — model_compose.cc).
//
// Both need the SAME sampling math (translation LERP, rotation SLERP, scale
// LERP, key bracketing) but live in different libraries. To avoid a renderer→
// assets dependency inversion, the interpolation lives here in `assets`.
#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

#include <assets/animation.h>

namespace assets {

/// Sample a single track's translation channel at time `t`, returning
/// `fallback` when the channel is empty. Linear interpolation between keys;
/// clamps at the endpoints.
glm::vec3 sample_track_translation(const AnimationClip::NodeTrack& tr, float t,
                                   const glm::vec3& fallback);

/// Sample a single track's rotation channel at time `t` (SLERP, normalized),
/// returning `fallback` when the channel is empty.
glm::quat sample_track_rotation(const AnimationClip::NodeTrack& tr, float t,
                                const glm::quat& fallback);

/// Sample a single track's scale channel at time `t` (LERP), returning
/// `fallback` when the channel is empty.
float sample_track_scale(const AnimationClip::NodeTrack& tr, float t,
                         float fallback);

/// Compose a track's sampled translation/rotation/scale at time `t` into a
/// local TRS matrix: T · R · S. `fallback_translation` / `fallback_rotation` /
/// `fallback_scale` supply the value for any channel the track omits — pass the
/// node's bind-pose components so an absent channel leaves that component at
/// bind. `t` is clamped to the clip's [0, duration] range by the caller.
glm::mat4 sample_track_trs(const AnimationClip::NodeTrack& tr, float t,
                           const glm::vec3& fallback_translation,
                           const glm::quat& fallback_rotation,
                           float fallback_scale);

}  // namespace assets
