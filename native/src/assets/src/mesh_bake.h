// native/src/assets/src/mesh_bake.h
#pragma once

#include <assets/mesh.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <vector>

namespace assets::detail {

/// Compose the model-space world transform of every node by walking the
/// `parent_index` chain from the root, multiplying each node's
/// `local_transform`. INCLUDES the root node's own local_transform and
/// EXCLUDES any per-instance transform. Result[i] is exactly what the
/// renderer's per-node draw computes as `world_per_node[i]` minus the
/// leading `inst.world` factor.
///
/// Precondition: `nodes` is topologically ordered (parents precede
/// children), which build_nodes guarantees.
std::vector<glm::mat4> compute_local_world_per_node(
    const std::vector<Node>& nodes, int root_node);

/// Transform every vertex of `cpu` from node-local space into model space by
/// the rigid transform `m`:
///   position -> m * vec4(pos, 1)
///   normal   -> normalize(mat3(m) * normal)
/// mat3(m) is correct for rotation+translation; under non-uniform node scale
/// the normal transform is approximate (the inverse-transpose would be exact),
/// which Bip01 character skeletons do not exercise.
void bake_mesh_to_model_space(MeshCpu& cpu, const glm::mat4& m);

}  // namespace assets::detail
