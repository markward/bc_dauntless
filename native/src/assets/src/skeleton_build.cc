#include "skeleton_build.h"
#include "link_resolver.h"

#include <nif/block.h>

#include <glm/gtc/matrix_inverse.hpp>

#include <set>
#include <vector>

namespace assets::detail {

namespace {

const nif::NiNode* node_at(const nif::File& f, std::uint32_t block_index) {
    if (block_index >= f.blocks.size()) return nullptr;
    return std::get_if<nif::NiNode>(&f.blocks[block_index]);
}

glm::mat4 av_to_local_transform(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
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

/// Maps block index → parent block index (or std::uint32_t::max for root).
std::unordered_map<std::uint32_t, std::uint32_t>
compute_parent_map(const nif::File& f, const LinkResolver& resolver) {
    std::unordered_map<std::uint32_t, std::uint32_t> parents;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto child_link : node->child_links) {
            auto child_idx = resolver.resolve(child_link);
            if (child_idx == LinkResolver::kInvalidIndex) continue;
            parents[child_idx] = i;
        }
    }
    return parents;
}

std::set<std::uint32_t> gather_bone_block_indices(
    const nif::File& f, const LinkResolver& resolver)
{
    std::set<std::uint32_t> bones;
    for (auto& b : f.blocks) {
        const auto* skin = std::get_if<nif::NiTriShapeSkinController>(&b);
        if (!skin) continue;
        for (auto link : skin->bone_links) {
            auto idx = resolver.resolve(link);
            if (idx != LinkResolver::kInvalidIndex) bones.insert(idx);
        }
    }
    return bones;
}

}  // namespace

SkeletonBuildResult build_skeleton(const nif::File& f) {
    SkeletonBuildResult out;
    LinkResolver resolver(f);
    auto bone_indices = gather_bone_block_indices(f, resolver);
    if (bone_indices.empty()) return out;

    auto parents = compute_parent_map(f, resolver);

    int next_index = 0;
    for (auto block_idx : bone_indices) {
        auto* node = node_at(f, block_idx);
        if (!node) continue;
        Bone b;
        b.name = node->av.obj.name;
        b.local_transform = av_to_local_transform(node->av);
        out.skeleton.bones.push_back(std::move(b));
        out.nif_block_to_bone_index[block_idx] = next_index++;
    }

    for (auto block_idx : bone_indices) {
        auto bit = out.nif_block_to_bone_index.find(block_idx);
        if (bit == out.nif_block_to_bone_index.end()) continue;
        int self_bone = bit->second;

        // Walk up the parent chain through any non-bone NiNodes until we
        // find another bone or hit the scene root. A skeleton like
        //   Pelvis(bone) -> Spine(plain NiNode) -> Chest(bone)
        // must record Chest's parent as Pelvis, not -1.
        int parent_bone = -1;
        for (auto current = parents.find(block_idx);
             current != parents.end();
             current = parents.find(current->second))
        {
            auto parent_bit = out.nif_block_to_bone_index.find(current->second);
            if (parent_bit != out.nif_block_to_bone_index.end()) {
                parent_bone = parent_bit->second;
                break;
            }
        }
        out.skeleton.bones[self_bone].parent_index = parent_bone;
    }

    for (std::size_t i = 0; i < out.skeleton.bones.size(); ++i) {
        if (out.skeleton.bones[i].parent_index == -1) {
            out.skeleton.root_bone_index = static_cast<int>(i);
            break;
        }
    }

    compute_inverse_bind_poses(out.skeleton);
    return out;
}

void compute_inverse_bind_poses(Skeleton& sk) {
    // world_bind(i) composed by walking up the parent chain. Bones are not
    // guaranteed to be parent-before-child ordered, so resolve each bone's
    // world transform by collecting its chain to the root.
    auto world_bind = [&](int i) {
        glm::mat4 w(1.0f);
        // Collect chain leaf..root, then multiply root..leaf.
        std::vector<int> chain;
        for (int b = i; b != -1; b = sk.bones[b].parent_index) chain.push_back(b);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            w = w * sk.bones[*it].local_transform;
        return w;
    };
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        sk.bones[i].inverse_bind_pose =
            glm::inverse(world_bind(static_cast<int>(i)));
}

}  // namespace assets::detail
