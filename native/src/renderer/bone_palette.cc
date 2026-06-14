// native/src/renderer/bone_palette.cc
#include "renderer/bone_palette.h"
#include <algorithm>
#include <cstdio>

namespace renderer {

std::vector<glm::mat4> build_bone_palette(
    const assets::Skeleton& sk,
    const std::vector<glm::mat4>* local_pose) {

    const std::size_t n = std::min(sk.bones.size(), kMaxBones);
    if (sk.bones.size() > kMaxBones) {
        std::fprintf(stderr,
            "[bone_palette] skeleton has %zu bones; clamping to %zu\n",
            sk.bones.size(), kMaxBones);
    }

    auto local_of = [&](std::size_t i) -> glm::mat4 {
        if (local_pose && i < local_pose->size()) return (*local_pose)[i];
        return sk.bones[i].local_transform;
    };

    // world_pose(i) = product of local transforms down the parent chain.
    // The chain-walk MUST traverse the full ancestry to the root (mirrors
    // assets::detail::compute_inverse_bind_poses in skeleton_build.cc): bones
    // are not parent-ordered, so an in-range bone (index < n) can have an
    // ancestor with index >= n. inverse_bind_pose composes the full chain with
    // no clamp, so this walk must too, or palette = world_bind * inverse_bind
    // would not collapse to identity at bind pose. Precondition: parent_index
    // values are acyclic and in range (see bone_palette.h). The kMaxBones clamp
    // applies only to the OUTER palette loop, not this inner walk.
    auto world_of = [&](int i) {
        glm::mat4 w(1.0f);
        std::vector<int> chain;
        for (int b = i; b != -1; b = sk.bones[b].parent_index)
            chain.push_back(b);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            w = w * local_of(static_cast<std::size_t>(*it));
        return w;
    };

    std::vector<glm::mat4> palette(n);
    for (std::size_t i = 0; i < n; ++i)
        palette[i] = world_of(static_cast<int>(i)) * sk.bones[i].inverse_bind_pose;
    return palette;
}

}  // namespace renderer
