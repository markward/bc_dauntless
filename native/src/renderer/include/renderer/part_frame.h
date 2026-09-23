// native/src/renderer/include/renderer/part_frame.h
#pragma once

#include <optional>
#include <unordered_map>

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// The transform that maps a POSED body-frame point back into the rest frame
/// of the overridden node whose geometry contains it — or nullopt when no
/// overridden node claims that point.
///
/// Every baked structure in this engine (the .dhv distance field, the carve
/// field, the trace BVH) is whole-hull, rest-pose and SHARED across every
/// instance of a model. So a query arriving in the LIVE pose is transformed
/// back into rest space rather than the structure being re-posed per
/// instance. This is the primitive that does it, and it is the same rule
/// ray_trace.cc follows from the other direction (there the RAY moves; here
/// the POINT does).
///
/// Returns nullopt for a SINGULAR override: a hidden or severed part is the
/// zero matrix, whose inverse is all NaN and would poison whatever field the
/// result were applied to.
///
/// An override names a PART node, but find_parent_node_index attaches a mesh
/// to its immediate NiNode parent, which on a real BC hull is an interposed
/// __NDL_MultiMtl_Node. So a node's geometry is its own meshes AND every
/// descendant's. Getting that wrong is what made manual fire miss a raised
/// wing live — see the spec's §5c child-node trap.
std::optional<glm::mat4> rest_from_posed_at(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides,
    const glm::vec3& body_point);

}  // namespace renderer
