#pragma once
#include <string>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; struct AnimationClip; }

namespace renderer {

/// Resolve a node NAME to its index, robust to DUPLICATE names. BC set models
/// NEST a duplicate: an outer node carrying the PLACEMENT and an identity-local
/// CHILD of the same name holding the mesh (DBridge.nif's [217]/[220] "console
/// seat 01"). `sample_node_overrides` binds the clip to the PLACED node, and
/// `compose_node_worlds` then moves that node's whole subtree (mesh child
/// included). A reader that resolved the name to the OTHER duplicate would see
/// no override. So: prefer the duplicate that carries an override in
/// `overrides`; otherwise the first node with the name; else -1. This keeps a
/// coupling read (anim vs rest, e.g. the chair->officer coupling) on the SAME
/// node the clip animates — both poses come from the placed node.
int resolve_overridden_node(
    const assets::Model& model, const std::string& name,
    const std::unordered_map<int, glm::mat4>& overrides);

/// Compose a world transform per node for a non-skinned model. For each node,
/// use `overrides[i]` as its local transform when present, else the model's
/// static `nodes[i].local_transform`; chain `parent_world * local`. The asset
/// pipeline orders nodes parent-before-child, so a single linear pass is
/// correct. Returns an empty vector when the model has no nodes. With an empty
/// `overrides` map this reproduces the static node walk exactly.
std::vector<glm::mat4> compose_node_worlds(
    const assets::Model& model, const glm::mat4& instance_world,
    const std::unordered_map<int, glm::mat4>& overrides);

/// Sample a clip's node tracks against a model at time `t`, returning a
/// node_index -> local_transform override for every track whose
/// target_node_name matches a model node. Tracks with no matching node (e.g. a
/// chair clip's baked "Camera captain" view-path) are skipped. `t` is clamped to
/// [0, clip.duration_seconds].
///
/// A clip's keys are the absolute local TRS of the PLACED node, in the set's own
/// frame (BC's NiKeyframeController overwrites its target node's local
/// outright). So the track is bound to the placed duplicate — the candidate node
/// whose own local TRANSLATION matches the clip's rest translation
/// (`AnimationClip::rest_locals`, the rest local of the clip's SOURCE NIF) — and
/// the sampled pose is written in DIRECTLY. Nothing is double-applied: the other
/// duplicate is an identity-local mesh child of the placed node. Each channel the
/// track omits falls back to the CLIP's rest for that channel.
///
/// Only the rest TRANSLATION is ever consulted. The rest ROTATION is unreliable:
/// BC bakes each *_reverse / *_in chair clip's rest local to that clip's FIRST
/// KEY rather than the set's rest pose (db_chair_H_face_capt_reverse rest =
/// Rz(-60), keys -60 -> 0).
///
/// FALLBACK, when no placed duplicate matches (a lone node whose placement lives
/// on a differently-named parent): retarget the motion as a delta against the
/// clip's own rest, applied in the model node's frame —
///
///     override = model_local * inverse(clip_rest) * clip_sampled
///
/// — since such keys are in the clip's OWN root frame and writing them straight
/// in would apply the parent's placement TWICE. This path DOES consult the rest
/// rotation, so it mirrors any rest-baked clip; it is a fallback, not the norm.
/// When the clip records no rest local at all, the sampled pose is used as the
/// node's local directly (the historic behaviour).
std::unordered_map<int, glm::mat4> sample_node_overrides(
    const assets::AnimationClip& clip, const assets::Model& model, float t);

}  // namespace renderer
