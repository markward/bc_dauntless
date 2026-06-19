#pragma once
#include <string>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; struct AnimationClip; }

namespace renderer {

/// Resolve a node NAME to its index, robust to DUPLICATE names. BC bridge
/// models contain two nodes with the same name (e.g. "console seat 01" appears
/// twice); `sample_node_overrides` keys its override on whichever index its
/// name->index map kept (last wins), and `compose_node_worlds` rotates that
/// node's subtree (the seat mesh). A reader that resolved the name to the OTHER
/// duplicate would see no override. So: prefer the duplicate that carries an
/// override in `overrides`; otherwise the first node with the name; else -1.
/// This keeps a coupling read (anim vs rest) on the SAME node the clip animates.
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
/// chair clip's baked "Camera captain" view-path) are skipped. Each omitted
/// channel (T/R/S) falls back to the node's static local. `t` is clamped to
/// [0, clip.duration_seconds].
std::unordered_map<int, glm::mat4> sample_node_overrides(
    const assets::AnimationClip& clip, const assets::Model& model, float t);

}  // namespace renderer
