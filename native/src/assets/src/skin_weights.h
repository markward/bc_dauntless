// native/src/assets/src/skin_weights.h
#pragma once
#include <vector>
#include <assets/mesh.h>
#include <nif/block.h>

namespace assets::detail {

/// Fill per-vertex bone_indices/bone_weights on `cpu` from a legacy
/// NiTriShapeSkinController. `skin_bone_to_skeleton[i]` maps the controller's
/// i-th bone (0..num_bones-1) to a Skeleton::bones index. Each vertex keeps its
/// 4 largest influences, renormalized so the four u8 weights sum to ~255.
/// Vertices with no influence get bone 0 at full weight.
void fill_skin_weights(MeshCpu& cpu,
                       const nif::NiTriShapeSkinController& skin,
                       const std::vector<int>& skin_bone_to_skeleton);

}  // namespace assets::detail
