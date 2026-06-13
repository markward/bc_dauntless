#include <gtest/gtest.h>
#include <renderer/bone_palette.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>

namespace {
assets::Skeleton two_bone_skeleton() {
    assets::Skeleton sk;
    assets::Bone root; root.parent_index = -1;
    root.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Bone child; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 3, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;
    // bind-pose inverse: inverse of composed world transform.
    sk.bones[0].inverse_bind_pose = glm::inverse(sk.bones[0].local_transform);
    sk.bones[1].inverse_bind_pose =
        glm::inverse(sk.bones[0].local_transform * sk.bones[1].local_transform);
    return sk;
}
bool near_identity(const glm::mat4& m, float eps = 1e-4f) {
    glm::mat4 I(1.0f);
    for (int c = 0; c < 4; ++c) for (int r = 0; r < 4; ++r)
        if (std::abs(m[c][r] - I[c][r]) > eps) return false;
    return true;
}
}

TEST(BonePalette, BindPoseYieldsIdentityPerBone) {
    auto sk = two_bone_skeleton();
    auto palette = renderer::build_bone_palette(sk, nullptr);
    ASSERT_EQ(palette.size(), 2u);
    EXPECT_TRUE(near_identity(palette[0]));
    EXPECT_TRUE(near_identity(palette[1]));
}

TEST(BonePalette, TranslatedRootPosePropagatesToChild) {
    auto sk = two_bone_skeleton();
    // Pose: shift root +X by 10, child unchanged in local frame.
    std::vector<glm::mat4> pose = {
        glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)) * sk.bones[0].local_transform,
        sk.bones[1].local_transform,
    };
    auto palette = renderer::build_bone_palette(sk, &pose);
    // A bind-pose child vertex at composed world position should translate +X10.
    glm::vec4 world_bind_child = sk.bones[0].local_transform
                               * sk.bones[1].local_transform * glm::vec4(0, 0, 0, 1);
    glm::vec4 moved = palette[1] * world_bind_child;
    EXPECT_NEAR(moved.x, world_bind_child.x + 10.0f, 1e-3f);
    EXPECT_NEAR(moved.y, world_bind_child.y, 1e-3f);
}

TEST(BonePalette, OutOfClampRangeAncestorYieldsIdentity) {
    // Regression for the truncated chain-walk bug. The clamp produces palette
    // entries only for the first n = min(bones, kMaxBones) bones, but bones are
    // NOT parent-ordered: an in-range bone (index < kMaxBones, so it DOES get a
    // palette entry) can have an ancestor at index >= kMaxBones. The old
    // `b < n` chain-walk guard dropped that ancestor from world_of while
    // inverse_bind_pose still composed the full chain -> the bind-pose palette
    // for the in-range bone was silently non-identity. Walking the full chain
    // restores the bind-pose identity invariant.
    constexpr std::size_t kMax = renderer::kMaxBones;  // 128
    assets::Skeleton sk;
    sk.bones.resize(kMax + 1);
    // Root lives PAST the clamp, at index kMax (>= kMaxBones).
    const int root = static_cast<int>(kMax);
    sk.bones[root].parent_index = -1;
    sk.bones[root].local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    // Bone 0 is in-range (gets a palette entry) but its parent is the root,
    // which is out of the clamp range.
    sk.bones[0].parent_index = root;
    sk.bones[0].local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 3, 0));
    // Remaining in-range bones are independent roots (parentless, identity).
    for (std::size_t i = 1; i < kMax; ++i) {
        sk.bones[i].parent_index = -1;
        sk.bones[i].local_transform = glm::mat4(1.0f);
    }
    sk.root_bone_index = root;
    // inverse_bind_pose = inverse of the full composed world transform.
    for (std::size_t i = 0; i < sk.bones.size(); ++i) {
        glm::mat4 w(1.0f);
        std::vector<int> chain;
        for (int b = static_cast<int>(i); b != -1; b = sk.bones[b].parent_index)
            chain.push_back(b);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            w = w * sk.bones[*it].local_transform;
        sk.bones[i].inverse_bind_pose = glm::inverse(w);
    }

    auto palette = renderer::build_bone_palette(sk, nullptr);
    ASSERT_EQ(palette.size(), kMax);  // clamped; root at index kMax has no entry
    // Bone 0's ancestor (the root) is past the clamp; full-chain walk must
    // still include it for the bind-pose palette to collapse to identity.
    EXPECT_TRUE(near_identity(palette[0]));
}

TEST(BonePalette, ClampsToMaxBones) {
    assets::Skeleton sk;
    for (int i = 0; i < 200; ++i) {
        assets::Bone b; b.parent_index = (i == 0 ? -1 : i - 1);
        b.local_transform = glm::mat4(1.0f);
        b.inverse_bind_pose = glm::mat4(1.0f);
        sk.bones.push_back(b);
    }
    sk.root_bone_index = 0;
    auto palette = renderer::build_bone_palette(sk, nullptr);
    EXPECT_EQ(palette.size(), renderer::kMaxBones);  // clamped to 128
}
