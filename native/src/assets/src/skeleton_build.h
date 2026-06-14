// native/src/assets/src/skeleton_build.h
#pragma once

#include <assets/skeleton.h>
#include <nif/file.h>

#include <cstdint>
#include <unordered_map>

namespace assets::detail {

struct SkeletonBuildResult {
    Skeleton skeleton;
    /// Maps NIF block index of every hierarchy NiNode → Skeleton::bones index.
    std::unordered_map<std::uint32_t, int> nif_block_to_bone_index;
};

/// If the model carries at least one NiTriShapeSkinController (i.e. it is a
/// character), build a Skeleton mirroring the FULL NiNode hierarchy: one Bone
/// per NiNode, parented to its actual parent NiNode, rooted at the model root.
/// This keeps the skeleton's world-bind aligned with the model's node bake and
/// keeps every animatable node (e.g. the "Bip01" root carrying the placement
/// clip's station-offset track) addressable by name. Returns an empty skeleton
/// when no skinning is present (typical for ships and bridges) so those models
/// keep their byte-identical static render path.
SkeletonBuildResult build_skeleton(const nif::File& file);

/// Fill every bone's inverse_bind_pose = inverse(world-bind transform),
/// where world-bind composes local_transform down the parent chain.
/// Precondition: parent_index values must be acyclic and in range (-1 or a
/// valid bone index); build_skeleton guarantees this. A malformed chain would
/// loop or read out of bounds.
void compute_inverse_bind_poses(Skeleton& skeleton);

}  // namespace assets::detail
