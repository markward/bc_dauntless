#include "skeleton_build.h"
#include "link_resolver.h"

#include <nif/block.h>

#include <glm/gtc/matrix_inverse.hpp>

#include <functional>
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

    // Gating: only models that carry at least one skin controller are
    // characters and get a skeleton. Ships and bridges have no skin
    // controller — they return an empty skeleton exactly as before, so the
    // rigid-bake / skinned-program path in build_model is never engaged for
    // them and the production render path stays byte-identical.
    auto bone_indices = gather_bone_block_indices(f, resolver);
    if (bone_indices.empty()) return out;

    // For a character, the skeleton mirrors the FULL NiNode hierarchy, not
    // just the skin-controller-referenced subset. This is what makes the
    // skeleton's world-bind match the Task-1 vertex bake (node_bind_world,
    // rooted at the model root) AND keeps the placement clip's "Bip01" root
    // node — whose root-translation track carries the station offset — as a
    // real bone that the pose sampler can drive by name.
    //
    // Walk the tree exactly the way build_nodes (model_build.cc) does: find
    // the root NiNode (a NiNode that no other NiNode lists as a child), then
    // recurse, assigning each NiNode one Bone with its actual parent bone
    // index (now never skipped, because every NiNode is a bone).
    std::unordered_map<std::uint32_t, int> ref_count;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto child_link : node->child_links) {
            auto child_idx = resolver.resolve(child_link);
            if (child_idx == LinkResolver::kInvalidIndex) continue;
            ref_count[child_idx]++;
        }
    }

    std::function<void(std::uint32_t, int)> walk =
        [&](std::uint32_t nif_idx, int parent_bone) {
            const auto* node = node_at(f, nif_idx);
            if (!node) return;
            Bone b;
            b.name = node->av.obj.name;
            b.local_transform = av_to_local_transform(node->av);
            b.parent_index = parent_bone;
            int self = static_cast<int>(out.skeleton.bones.size());
            out.skeleton.bones.push_back(std::move(b));
            out.nif_block_to_bone_index[nif_idx] = self;

            for (auto child_link : node->child_links) {
                auto child_idx = resolver.resolve(child_link);
                if (child_idx != LinkResolver::kInvalidIndex)
                    walk(child_idx, self);
            }
        };

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        if (!std::get_if<nif::NiNode>(&f.blocks[i])) continue;
        if (ref_count[i] == 0) {
            out.skeleton.root_bone_index = static_cast<int>(out.skeleton.bones.size());
            walk(i, /*parent_bone=*/-1);
            break;  // BC files have a single root NiNode
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
