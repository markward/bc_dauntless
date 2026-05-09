#include "skeleton_build.h"

#include <nif/block.h>

#include <set>

namespace assets::detail {

namespace {

struct ParentMap {
    /// nif block index → parent nif block index (or -1 for root)
    std::unordered_map<std::uint32_t, std::int64_t> parents;
};

ParentMap compute_parent_map(const nif::File& f) {
    ParentMap map;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto child : node->child_links) {
            map.parents[child] = static_cast<std::int64_t>(i);
        }
    }
    return map;
}

std::set<std::uint32_t> gather_bone_block_indices(const nif::File& f) {
    std::set<std::uint32_t> bones;
    for (auto& b : f.blocks) {
        const auto* skin = std::get_if<nif::NiTriShapeSkinController>(&b);
        if (!skin) continue;
        for (auto link : skin->bone_links) bones.insert(link);
    }
    return bones;
}

const nif::NiNode* node_at(const nif::File& f, std::uint32_t idx) {
    if (idx >= f.blocks.size()) return nullptr;
    return std::get_if<nif::NiNode>(&f.blocks[idx]);
}

glm::mat4 av_to_local_transform(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    // nif::Mat3x3 is row-major; glm::mat4 columns are vec4s. Transpose to columns.
    m[0] = glm::vec4(av.rotation.m[0], av.rotation.m[3], av.rotation.m[6], 0.0f);
    m[1] = glm::vec4(av.rotation.m[1], av.rotation.m[4], av.rotation.m[7], 0.0f);
    m[2] = glm::vec4(av.rotation.m[2], av.rotation.m[5], av.rotation.m[8], 0.0f);
    m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
    if (av.scale != 1.0f) {
        m[0] *= av.scale;
        m[1] *= av.scale;
        m[2] *= av.scale;
    }
    return m;
}

}  // namespace

SkeletonBuildResult build_skeleton(const nif::File& f) {
    SkeletonBuildResult out;
    auto bone_indices = gather_bone_block_indices(f);
    if (bone_indices.empty()) return out;

    auto parents = compute_parent_map(f);

    int next_index = 0;
    for (auto nif_idx : bone_indices) {
        auto* node = node_at(f, nif_idx);
        if (!node) continue;
        Bone b;
        b.name = node->av.obj.name;
        b.local_transform = av_to_local_transform(node->av);
        // inverse_bind_pose left as identity in v1; computed by walking world
        // transforms when the scene-graph runtime arrives.
        out.skeleton.bones.push_back(std::move(b));
        out.nif_block_to_bone_index[nif_idx] = next_index++;
    }

    for (auto nif_idx : bone_indices) {
        auto bit = out.nif_block_to_bone_index.find(nif_idx);
        if (bit == out.nif_block_to_bone_index.end()) continue;
        int self_bone = bit->second;
        auto pit = parents.parents.find(nif_idx);
        if (pit == parents.parents.end() || pit->second < 0) {
            out.skeleton.bones[self_bone].parent_index = -1;
            continue;
        }
        auto parent_nif = static_cast<std::uint32_t>(pit->second);
        auto parent_bit = out.nif_block_to_bone_index.find(parent_nif);
        out.skeleton.bones[self_bone].parent_index =
            (parent_bit != out.nif_block_to_bone_index.end())
                ? parent_bit->second
                : -1;
    }

    for (std::size_t i = 0; i < out.skeleton.bones.size(); ++i) {
        if (out.skeleton.bones[i].parent_index == -1) {
            out.skeleton.root_bone_index = static_cast<int>(i);
            break;
        }
    }
    return out;
}

}  // namespace assets::detail
