#pragma once
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; }

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

}  // namespace renderer
