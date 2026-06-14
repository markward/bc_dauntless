#include <cmath>

#include <gtest/gtest.h>
#include <renderer/pose_sampler.h>
#include <assets/animation.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace {
assets::Skeleton two_bone() {
    assets::Skeleton sk;
    assets::Bone root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Bone child; child.name = "child"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 1, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;
    return sk;
}
}

TEST(SamplePose, TracklessBoneKeepsBindLocal) {
    auto sk = two_bone();
    assets::AnimationClip clip;            // no tracks
    clip.duration_seconds = 1.0f;
    auto pose = renderer::sample_pose(clip, sk, 1.0f);
    ASSERT_EQ(pose.size(), 2u);
    EXPECT_EQ(pose[0], sk.bones[0].local_transform);
    EXPECT_EQ(pose[1], sk.bones[1].local_transform);
}

TEST(SamplePose, TranslationLerpsAtMidTime) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    t.translation = { {0.0f, glm::vec3(0, 0, 0)}, {2.0f, glm::vec3(0, 0, 10)} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, 1.0f);   // midpoint
    // child local should be a pure translation of (0,0,5).
    EXPECT_NEAR(pose[1][3].z, 5.0f, 1e-4f);
}

TEST(SamplePose, RestFrameTakesFinalKey) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    t.translation = { {0.0f, glm::vec3(0,0,0)}, {2.0f, glm::vec3(0,0,10)} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, clip.duration_seconds);
    EXPECT_NEAR(pose[1][3].z, 10.0f, 1e-4f);
}

TEST(SamplePose, RotationSlerps) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    glm::quat q0(1,0,0,0);                                   // identity
    glm::quat q1 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    t.rotation = { {0.0f, q0}, {2.0f, q1} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, 1.0f);       // ~45 deg
    glm::vec3 x = glm::vec3(pose[1] * glm::vec4(1, 0, 0, 0));
    EXPECT_NEAR(x.x, std::cos(glm::radians(45.0f)), 1e-3f);
    EXPECT_NEAR(x.y, std::sin(glm::radians(45.0f)), 1e-3f);
}
