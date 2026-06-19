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

TEST(SamplePoseOverBase, RootStaysAtBaseWhenGestureHasNoRootTrack) {
    assets::Skeleton sk;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0,5,0));
    sk.bones = {b0, b1}; sk.root_bone_index = 0;

    // Gesture: only j1 has a rotation track; NO Bip01 track. Its own rest_locals
    // would drop Bip01 to identity/origin — the bug we are layering away from.
    assets::AnimationClip g; g.name = "g"; g.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tj; tj.target_node_name = "j1";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    tj.rotation = {{0.0f, q}, {1.0f, q}};
    g.tracks = {tj};
    g.rest_locals["Bip01"] = glm::mat4(1.0f);          // origin — must be ignored
    g.rest_locals["j1"]    = b1.local_transform;

    // base_locals = the placement pose: Bip01 translated to a "station".
    std::vector<glm::mat4> base(2);
    base[0] = glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23)); // station root
    base[1] = b1.local_transform;

    auto out = renderer::sample_pose_over_base(g, sk, 0.5f, base);
    ASSERT_EQ(out.size(), 2u);
    // Root keeps the station translation from base_locals, NOT the clip rest origin.
    EXPECT_TRUE(glm::all(glm::epsilonEqual(glm::vec3(out[0][3]),
                                           glm::vec3(33, -104, 23), 1e-4f)));
    // j1 got the gesture's 90deg-Z rotation (its column 0 rotated toward +Y).
    glm::vec3 col0 = glm::normalize(glm::vec3(out[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-3f);
}

TEST(SamplePoseOverBase, UntrackedBoneTakesBaseExactly) {
    assets::Skeleton sk;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1; b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0; b1.local_transform = glm::mat4(1.0f);
    sk.bones = {b0, b1}; sk.root_bone_index = 0;
    assets::AnimationClip g; g.name = "g"; g.duration_seconds = 1.0f;  // no tracks at all
    std::vector<glm::mat4> base(2);
    base[0] = glm::translate(glm::mat4(1.0f), glm::vec3(1,2,3));
    base[1] = glm::translate(glm::mat4(1.0f), glm::vec3(4,5,6));
    auto out = renderer::sample_pose_over_base(g, sk, 0.0f, base);
    EXPECT_EQ(out[0], base[0]);
    EXPECT_EQ(out[1], base[1]);
}
