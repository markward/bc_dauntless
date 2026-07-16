#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <glm/gtx/quaternion.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/animation_update.h>
#include <renderer/channel_binder.h>

namespace {
// Model with TWO clips:
//   clip[0] = placement: root translated to (33,-104,23); j1 has no track.
//   clip[1] = gesture:   j1 rotated 90deg-Z; root has NO track (partial).
// Used to test layer_over_rest: the gesture should keep root at the station.
assets::Model two_clip_layered_model() {
    assets::Model m;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.skeleton.bones = {b0, b1};
    m.skeleton.root_bone_index = 0;
    m.skeleton.bones[0].inverse_bind_pose = glm::mat4(1.0f);
    m.skeleton.bones[1].inverse_bind_pose = glm::inverse(b1.local_transform);

    // placement clip: root translated to station; constant, no tracks needed.
    // We use rest_locals to embed the station offset so sample_pose returns it.
    assets::AnimationClip placement; placement.name = "place";
    placement.duration_seconds = 1.0f;
    placement.rest_locals["Bip01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23));
    placement.rest_locals["j1"] = b1.local_transform;
    // No tracks — sample_pose will return rest_locals for each bone.

    // gesture clip: only j1 animated (90deg-Z); NO Bip01 track.
    assets::AnimationClip gesture; gesture.name = "gesture";
    gesture.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr; tr.target_node_name = "j1";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    tr.rotation = {{0.0f, q}, {1.0f, q}};
    gesture.tracks = {tr};
    // gesture.rest_locals intentionally empty — root falls back to base_locals.

    m.animations = {placement, gesture};
    return m;
}

assets::Model two_bone_model_with_clip() {
    assets::Model m;
    // skeleton: bone0 root at origin, bone1 child translated +Y by 10.
    assets::Bone b0; b0.name = "root"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0,10,0));
    m.skeleton.bones = {b0, b1};
    m.skeleton.root_bone_index = 0;
    // inverse-bind = inverse(world_bind)
    m.skeleton.bones[0].inverse_bind_pose = glm::inverse(b0.local_transform);
    m.skeleton.bones[1].inverse_bind_pose =
        glm::inverse(b0.local_transform * b1.local_transform);
    // clip: rotate j1 90deg about Z, single key at t=0 and t=1.
    assets::AnimationClip clip; clip.name = "c"; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr; tr.target_node_name = "j1";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    tr.rotation = {{0.0f, q}, {1.0f, q}};
    clip.tracks = {tr};
    m.animations = {clip};
    return m;
}

// Model whose clip TRANSLATES the root (Bip01) over time: (0,0,0) at t=0 to
// (100,0,0) at t=1. Used to verify walk playback applies root motion (unlike
// layer_over_rest gestures, which anchor the root).
assets::Model root_motion_model() {
    assets::Model m;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    m.skeleton.bones = {b0};
    m.skeleton.root_bone_index = 0;
    m.skeleton.bones[0].inverse_bind_pose = glm::mat4(1.0f);

    assets::AnimationClip clip; clip.name = "walk"; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr; tr.target_node_name = "Bip01";
    tr.translation = {{0.0f, glm::vec3(0, 0, 0)}, {1.0f, glm::vec3(100, 0, 0)}};
    clip.tracks = {tr};
    m.animations = {clip};
    return m;
}
}

TEST(AnimationUpdate, PlayOnceHoldRebuildsThenSettles) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::bind_clip(*world.get(id), model, 0, {}, /*now=*/100.0);

    renderer::update_animations(world, lookup, 100.5);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);

    renderer::update_animations(world, lookup, 200.0);
    EXPECT_FALSE(world.get(id)->anim.dirty);
    auto settled_palette = world.get(id)->bone_palette;
    ASSERT_EQ(settled_palette.size(), 2u);

    // Content check — identical math to the historical test.
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin =
        (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        settled_palette[1] * probe, expect_skin * probe, 1e-4f)));

    // Settled ⇒ later frames rebuild nothing (palette bit-identical).
    renderer::update_animations(world, lookup, 300.0);
    for (std::size_t b = 0; b < settled_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], settled_palette[b]);
}

TEST(AnimationUpdate, GestureBindLeavesOtherBonesOnTheirIdle) {
    // THE structural fix: a gesture binding one bone must not evict the
    // looping idle from the others. two_clip_layered_model: clip[0]=placement
    // (rest_locals station), clip[1]=gesture (j1 only).
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    scenegraph::Instance& inst = *world.get(id);

    renderer::set_rest_pose(inst, model, 0, /*at_start=*/false);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model, 1, idle, 0.0);      // j1 loops
    renderer::update_animations(world, lookup, 0.25);

    // Re-bind the same gesture one-shot at t=10 (simulates gesture over idle
    // on the SAME bone — last-bind-wins) and verify the root stayed at the
    // station throughout (it was never bound by either clip).
    renderer::bind_clip(inst, model, 1, {}, 10.0);
    renderer::update_animations(world, lookup, 10.5);
    glm::vec4 root_world = world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(root_world), glm::vec3(33, -104, 23), 1e-3f)));
}

TEST(AnimationUpdate, LoopingIdleStaysAnchoredAndNeverSettles) {
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    scenegraph::Instance& inst = *world.get(id);
    renderer::set_rest_pose(inst, model, 0, false);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model, 1, idle, 0.0);

    auto root_world_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return glm::vec3(world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1));
    };
    glm::vec3 r1 = root_world_at(0.3);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    glm::vec3 r2 = root_world_at(50.0);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r1, glm::vec3(33,-104,23), 1e-3f)));
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r2, glm::vec3(33,-104,23), 1e-3f)));
}

TEST(AnimationUpdate, WalkBindAppliesRootMotionAndPlaysThrough) {
    assets::Model model = root_motion_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::BindOptions walk; walk.root_motion = true; walk.use_clip_base = true;
    renderer::bind_clip(*world.get(id), model, 0, walk, 100.0);

    auto root_x_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return (world.get(id)->bone_palette[0] * glm::vec4(0, 0, 0, 1)).x;
    };
    EXPECT_NEAR(root_x_at(100.0), 0.0f, 1e-3f);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_NEAR(root_x_at(100.5), 50.0f, 1e-3f);
    EXPECT_NEAR(root_x_at(200.0), 100.0f, 1e-3f);
    EXPECT_FALSE(world.get(id)->anim.dirty);
}

TEST(AnimationUpdate, RestPoseHoldsStartFrameWhenAtStart) {
    // Replaces SampleAtStartHoldsStartFrameAndSettles: at_start rest = t0 hold.
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::set_rest_pose(*world.get(id), model, 0, /*at_start=*/true);

    renderer::update_animations(world, lookup, 100.5);
    auto palette = world.get(id)->bone_palette;
    ASSERT_EQ(palette.size(), 2u);
    EXPECT_FALSE(world.get(id)->anim.dirty);

    // The single 90°-Z key is constant, so t=0 carries the rotation too.
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin =
        (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        palette[1] * probe, expect_skin * probe, 1e-4f)));

    renderer::update_animations(world, lookup, 500.0);
    for (std::size_t b = 0; b < palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], palette[b]);
}
