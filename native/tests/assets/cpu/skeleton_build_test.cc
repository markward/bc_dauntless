#include <gtest/gtest.h>
#include "skeleton_build.h"

#include <nif/block.h>
#include <nif/file.h>

#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>

#include <cmath>

// Helper exposed for testing: fills inverse_bind_pose for every bone from
// the bones' local_transform + parent_index chain.
namespace assets::detail { void compute_inverse_bind_poses(Skeleton&); }

namespace {

bool mat_near(const glm::mat4& a, const glm::mat4& b, float eps = 1e-4f) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 4; ++r)
            if (std::abs(a[c][r] - b[c][r]) > eps) return false;
    return true;
}


// Synthetic file: Root → Pelvis → Spine → Arm, with a NiTriShapeSkinController
// referencing the three bones.
nif::File build_synthetic_skinned_file() {
    nif::File f;
    {
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
    }
    {
        nif::NiNode b;
        b.av.obj.name = "Pelvis";
        b.av.translation = {0, 0, 1};
        b.child_links = {2};
        f.blocks.push_back(b);
    }
    {
        nif::NiNode b;
        b.av.obj.name = "Spine";
        b.av.translation = {0, 0, 2};
        b.child_links = {3};
        f.blocks.push_back(b);
    }
    {
        nif::NiNode b;
        b.av.obj.name = "Arm";
        b.av.translation = {1, 0, 2};
        f.blocks.push_back(b);
    }
    {
        nif::NiTriShapeSkinController c;
        c.num_bones = 3;
        c.bone_links = {1, 2, 3};
        f.blocks.push_back(c);
    }
    return f;
}

int find_bone(const assets::Skeleton& s, const std::string& name) {
    for (std::size_t i = 0; i < s.bones.size(); ++i)
        if (s.bones[i].name == name) return static_cast<int>(i);
    return -1;
}

}  // namespace

TEST(SkeletonBuild, NoSkinningProducesEmptySkeleton) {
    nif::File f;
    nif::NiNode root;
    root.av.obj.name = "Root";
    f.blocks.push_back(root);

    auto result = assets::detail::build_skeleton(f);
    EXPECT_TRUE(result.skeleton.bones.empty());
    EXPECT_EQ(result.skeleton.root_bone_index, -1);
}

TEST(SkeletonBuild, FlattensBonesWithParentIndices) {
    auto f = build_synthetic_skinned_file();
    auto result = assets::detail::build_skeleton(f);

    ASSERT_EQ(result.skeleton.bones.size(), 3u);
    int pelvis = find_bone(result.skeleton, "Pelvis");
    int spine  = find_bone(result.skeleton, "Spine");
    int arm    = find_bone(result.skeleton, "Arm");
    ASSERT_NE(pelvis, -1);
    ASSERT_NE(spine, -1);
    ASSERT_NE(arm, -1);

    EXPECT_EQ(result.skeleton.bones[pelvis].parent_index, -1);
    EXPECT_EQ(result.skeleton.bones[spine].parent_index, pelvis);
    EXPECT_EQ(result.skeleton.bones[arm].parent_index, spine);
}

TEST(SkeletonBuild, NifBlockIndexMapPopulated) {
    auto f = build_synthetic_skinned_file();
    auto result = assets::detail::build_skeleton(f);

    EXPECT_TRUE(result.nif_block_to_bone_index.count(1));
    EXPECT_TRUE(result.nif_block_to_bone_index.count(2));
    EXPECT_TRUE(result.nif_block_to_bone_index.count(3));
}

TEST(SkeletonBuild, IdentifiesRoot) {
    auto f = build_synthetic_skinned_file();
    auto result = assets::detail::build_skeleton(f);
    ASSERT_NE(result.skeleton.root_bone_index, -1);
    EXPECT_EQ(
        result.skeleton.bones[result.skeleton.root_bone_index].name,
        "Pelvis");
}

TEST(InverseBindPose, BindPosePaletteIsIdentityPerBone) {
    // Root translated +X by 2; child translated +Y by 3 in root's local frame.
    assets::Skeleton sk;
    assets::Bone root;  root.name = "root";  root.parent_index = -1;
    root.local_transform  = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Bone child; child.name = "child"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 3, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;

    assets::detail::compute_inverse_bind_poses(sk);

    // world_bind(child) = T(+x2) * T(+y3); palette at bind = world_bind * inverse_bind == I.
    glm::mat4 world_root  = sk.bones[0].local_transform;
    glm::mat4 world_child = world_root * sk.bones[1].local_transform;
    EXPECT_TRUE(mat_near(world_root  * sk.bones[0].inverse_bind_pose, glm::mat4(1.0f)));
    EXPECT_TRUE(mat_near(world_child * sk.bones[1].inverse_bind_pose, glm::mat4(1.0f)));
    // child inverse-bind must equal inverse of its composed world transform.
    EXPECT_TRUE(mat_near(sk.bones[1].inverse_bind_pose, glm::inverse(world_child)));
}

TEST(SkeletonBuild, ParentWalkThroughNonBoneNiNode) {
    // Hierarchy: Root(0) -> Pelvis(1, bone) -> SpineHelper(2, plain NiNode)
    //                                          -> Chest(3, bone)
    // SpineHelper is NOT in the skin's bone_links; Chest's parent should
    // resolve transitively to Pelvis, not -1.
    nif::File f;
    {
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
    }
    {
        nif::NiNode pelvis;
        pelvis.av.obj.name = "Pelvis";
        pelvis.child_links = {2};
        f.blocks.push_back(pelvis);
    }
    {
        nif::NiNode helper;
        helper.av.obj.name = "SpineHelper";  // NOT skinned to
        helper.child_links = {3};
        f.blocks.push_back(helper);
    }
    {
        nif::NiNode chest;
        chest.av.obj.name = "Chest";
        f.blocks.push_back(chest);
    }
    {
        nif::NiTriShapeSkinController c;
        c.num_bones = 2;
        c.bone_links = {1, 3};  // only Pelvis and Chest are bones
        f.blocks.push_back(c);
    }

    auto result = assets::detail::build_skeleton(f);
    ASSERT_EQ(result.skeleton.bones.size(), 2u);

    int pelvis = find_bone(result.skeleton, "Pelvis");
    int chest  = find_bone(result.skeleton, "Chest");
    ASSERT_NE(pelvis, -1);
    ASSERT_NE(chest, -1);
    EXPECT_EQ(result.skeleton.bones[pelvis].parent_index, -1);
    EXPECT_EQ(result.skeleton.bones[chest].parent_index, pelvis)
        << "Chest's parent should walk through SpineHelper to Pelvis";
}
