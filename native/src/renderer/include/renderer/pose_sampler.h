// native/src/renderer/include/renderer/pose_sampler.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <assets/animation.h>
#include <assets/skeleton.h>

namespace renderer {

/// Sample an animation clip at time `t` into per-bone LOCAL transforms
/// (indexed by skeleton bone). Tracks are matched to bones by
/// NodeTrack::target_node_name == Bone::name. Translation/scale LERP,
/// rotation SLERP between surrounding keys; `t` is clamped to [0, duration].
/// Bones with no matching track keep their bind local_transform. Feed the
/// result to build_bone_palette(skeleton, &pose).
///
/// Per-channel fallback within a track is asymmetric: a channel the track
/// OMITS falls back to bind translation, but identity rotation and unit
/// scale (NOT bind rotation/scale). This is correct for rotation-driven
/// skeletal clips (the common case — e.g. BC placement clips, where bones
/// carry rotation and the root carries translation). A hypothetical
/// translation-only track would drop the bone's bind rotation; if SP2 hits
/// such clips, derive the rotation/scale fallback from the bind matrix.
std::vector<glm::mat4> sample_pose(const assets::AnimationClip& clip,
                                   const assets::Skeleton& skeleton,
                                   float t);

}  // namespace renderer
