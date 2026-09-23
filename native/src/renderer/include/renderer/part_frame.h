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
/// CONTAINMENT IS TESTED IN REST SPACE, NOT POSED SPACE. The query point is
/// pulled back into a candidate node's rest frame FIRST; only then is it
/// tested against that node's REST-pose subtree AABB. Testing the POSED
/// AABB instead (the box that bounds the subtree after the override's
/// rotation is applied) is unsound: for a rotated slab that box is far
/// larger than the slab itself and sweeps across neighbouring geometry, so a
/// fuselage hit between two deflected wings would land inside a wing's posed
/// box and get dragged onto the wing that wasn't struck. The rest box has no
/// such slack — it hugs the slab in its own frame regardless of the
/// override.
///
/// The rest box does not depend on the override at all, so it is IN
/// PRINCIPLE reusable across every carve and every instance of the hull —
/// but this function recomputes it per call rather than caching it behind a
/// bare `const assets::Model*`. That is deliberate: `assets::Model::
/// trace_accel`'s own doc comment (model.h) names exactly this hazard — a
/// freed model's address reused by a later allocation would silently serve
/// a PREVIOUS model's cached geometry. A safe cache would have to live
/// inside the Model itself (as trace_accel does), which is out of this
/// function's scope. In return, this only runs while an instance's
/// `node_overrides` is non-empty — an actively articulated part, not the
/// common case — so the per-call walk is cheap in the cases that reach it.
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
///
/// TIE-BREAK. When more than one overridden node's rest box claims the
/// point (e.g. port and starboard wing roots overlapping near the spine),
/// the winner is the SMALLEST rest-box volume, ties broken by the LOWEST
/// node index — a stated rule rather than `unordered_map` hash order, so two
/// instances of the same hull carve an overlapping hit identically and the
/// result does not change between runs.
std::optional<glm::mat4> rest_from_posed_at(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides,
    const glm::vec3& body_point);

}  // namespace renderer
