// native/src/assets/src/skeleton_build.h
#pragma once

#include <assets/skeleton.h>
#include <nif/file.h>

#include <cstdint>
#include <unordered_map>

namespace assets::detail {

struct SkeletonBuildResult {
    Skeleton skeleton;
    /// Maps NIF block index of a NiNode used as a bone → Skeleton::bones index.
    std::unordered_map<std::uint32_t, int> nif_block_to_bone_index;
};

/// Walk all NiTriShapeSkinController blocks; gather the bones they reference;
/// build a flat Skeleton with parent indices derived from the scene graph.
/// Returns an empty skeleton if no skinning is present (typical for ships).
SkeletonBuildResult build_skeleton(const nif::File& file);

/// Fill every bone's inverse_bind_pose = inverse(world-bind transform),
/// where world-bind composes local_transform down the parent chain.
void compute_inverse_bind_poses(Skeleton& skeleton);

}  // namespace assets::detail
