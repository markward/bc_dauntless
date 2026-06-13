#include <gtest/gtest.h>
#include <renderer/bone_palette.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>

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
