#pragma once
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; struct AnimationClip; }

namespace renderer {

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
