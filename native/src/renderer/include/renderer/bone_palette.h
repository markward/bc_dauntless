// native/src/renderer/include/renderer/bone_palette.h
#pragma once
#include <cstddef>
#include <vector>
#include <glm/glm.hpp>
#include <assets/skeleton.h>

namespace renderer {

/// Maximum bones in the skinning palette (matches u_bones[128] in skinned.vert).
inline constexpr std::size_t kMaxBones = 128;

/// Build the skinning palette: palette[b] = world_pose(b) * inverse_bind_pose(b).
/// `local_pose`, if non-null, supplies a local transform per bone (same order as
/// skeleton.bones); when null, each bone's bind local_transform is used (so the
/// palette is identity per bone). Result clamped to kMaxBones with a warning.
std::vector<glm::mat4> build_bone_palette(
    const assets::Skeleton& skeleton,
    const std::vector<glm::mat4>* local_pose);

}  // namespace renderer
