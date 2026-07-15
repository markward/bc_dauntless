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

/// Layered sample: like sample_pose, but each bone's BASE comes from
/// `base_locals` (per-bone local transforms, same order as skeleton.bones)
/// instead of the clip's own rest_locals/bind. Bones the clip does NOT track
/// are copied verbatim from base_locals; tracked bones sample their track over
/// the decomposed base_locals value (so an omitted channel — e.g. the root
/// translation gestures never carry — falls back to base_locals, keeping the
/// officer anchored at the placement pose). base_locals.size() must equal
/// skeleton.bones.size().
std::vector<glm::mat4> sample_pose_over_base(
    const assets::AnimationClip& clip, const assets::Skeleton& skeleton,
    float t, const std::vector<glm::mat4>& base_locals);

/// True iff any of the clip's tracks targets a bone of `skeleton` (exact,
/// case-sensitive name match — BC's own binding rule: stbc.exe binds clip
/// channels to nodes via full-string strcmp and silently idles every
/// unmatched node). A clip for which this is false is dead ballast on this
/// skeleton (e.g. the "Kiska …"-rigged Console_Look_*.NIF gestures on the
/// "Bip01 …" officer rigs) and must not replace a playing animation: BC shows
/// nothing for such clips, while sampling one would freeze the officer at the
/// layered base pose for the clip's duration.
bool clip_drives_skeleton(const assets::AnimationClip& clip,
                          const assets::Skeleton& skeleton);

}  // namespace renderer
