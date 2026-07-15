// bind_clip: BC's channel join — exact case-sensitive full-string strcmp of
// clip track names against skeleton bone names; hit = rebind that bone's
// channel (seeding the blend-from pose), miss = track dropped silently;
// untouched bones keep their previous channel (last-bind-wins per node).
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/channel_binder.h>

namespace {

// Skeleton: "Bip01" root, children "Bip01 Head" (+Y 5) and "Bip01 Spine" (+Y 2).
assets::Model three_bone_model() {
    assets::Model m;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "Bip01 Head"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    assets::Bone b2; b2.name = "Bip01 Spine"; b2.parent_index = 0;
    b2.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 2, 0));
    m.skeleton.bones = {b0, b1, b2};
    m.skeleton.root_bone_index = 0;
    for (auto& b : m.skeleton.bones) b.inverse_bind_pose = glm::mat4(1.0f);
    return m;
}

assets::AnimationClip clip_tracking(std::initializer_list<const char*> names,
                                    float dur = 1.0f) {
    assets::AnimationClip c; c.name = "c"; c.duration_seconds = dur;
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    for (const char* n : names) {
        assets::AnimationClip::NodeTrack tr; tr.target_node_name = n;
        tr.rotation = {{0.0f, q}, {dur, q}};
        c.tracks.push_back(tr);
    }
    return c;
}

}  // namespace

TEST(BindClip, ExactStrcmpJoinBindsOnlyMatchedBones) {
    assets::Model m = three_bone_model();
    // Track 0 matches "Bip01 Head"; track 1 ("Kiska Head") and track 2
    // ("bip01 spine" — wrong case) are dead ballast, BC-style.
    m.animations = {clip_tracking({"Bip01 Head", "Kiska Head", "bip01 spine"})};

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    int bound = renderer::bind_clip(inst, m, 0, {}, /*now=*/10.0);
    EXPECT_EQ(bound, 1);
    ASSERT_EQ(inst.anim.channels.size(), 3u);
    EXPECT_EQ(inst.anim.channels[0].clip_index, -1);   // Bip01 untouched
    EXPECT_EQ(inst.anim.channels[1].clip_index, 0);    // Bip01 Head bound
    EXPECT_EQ(inst.anim.channels[1].track_index, 0);
    EXPECT_EQ(inst.anim.channels[1].start_wall_time, 10.0);
    EXPECT_EQ(inst.anim.channels[2].clip_index, -1);   // Bip01 Spine untouched
    EXPECT_TRUE(inst.anim.dirty);
}

TEST(BindClip, ZeroMatchClipBindsNothingAndMutatesNothing) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"}),      // clip 0: idle
                    clip_tracking({"Kiska Head"})};     // clip 1: dead
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    ASSERT_EQ(renderer::bind_clip(inst, m, 0, {}, 1.0), 1);
    auto before = inst.anim.channels;   // copy
    inst.anim.dirty = false;            // simulate a settled frame

    EXPECT_EQ(renderer::bind_clip(inst, m, 1, {}, 2.0), 0);
    EXPECT_FALSE(inst.anim.dirty) << "dead clip must not re-dirty";
    ASSERT_EQ(inst.anim.channels.size(), before.size());
    for (std::size_t i = 0; i < before.size(); ++i)
        EXPECT_EQ(inst.anim.channels[i].clip_index, before[i].clip_index);
}

TEST(BindClip, LastBindWinsPerBoneOnly) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head", "Bip01 Spine"}),  // breathe
                    clip_tracking({"Bip01 Head"})};                // gesture
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::BindOptions loop_opts; loop_opts.loop = true;
    ASSERT_EQ(renderer::bind_clip(inst, m, 0, loop_opts, 1.0), 2);
    ASSERT_EQ(renderer::bind_clip(inst, m, 1, {}, 5.0), 1);

    EXPECT_EQ(inst.anim.channels[1].clip_index, 1);   // head → gesture
    EXPECT_FALSE(inst.anim.channels[1].loop);
    EXPECT_EQ(inst.anim.channels[1].start_wall_time, 5.0);
    EXPECT_EQ(inst.anim.channels[2].clip_index, 0);   // spine keeps breathe
    EXPECT_TRUE(inst.anim.channels[2].loop);
    EXPECT_EQ(inst.anim.channels[2].start_wall_time, 1.0);
}

TEST(BindClip, SeedComesFromLastLocalsThenRestThenBind) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"})};
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    // No last_locals, no rest → seed = bind local (+Y 5).
    renderer::bind_clip(inst, m, 0, {}, 0.0);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        inst.anim.channels[1].seed_t, glm::vec3(0, 5, 0), 1e-5f)));

    // With last_locals present → seed = last evaluated local.
    inst.anim.last_locals.assign(3, glm::mat4(1.0f));
    inst.anim.last_locals[1] =
        glm::translate(glm::mat4(1.0f), glm::vec3(7, 8, 9));
    renderer::bind_clip(inst, m, 0, {}, 1.0);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        inst.anim.channels[1].seed_t, glm::vec3(7, 8, 9), 1e-5f)));
}

TEST(BindClip, BlendFlagUsesBcFormulaOtherwiseZero) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"}, /*dur=*/1.0f),
                    clip_tracking({"Bip01 Head"}, /*dur=*/0.1f)};
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::bind_clip(inst, m, 0, {}, 0.0);          // blend=false default
    EXPECT_EQ(inst.anim.channels[1].blend_in_s, 0.0f);

    renderer::BindOptions b; b.blend = true;
    renderer::bind_clip(inst, m, 0, b, 0.0);           // dur 1.0 ≥ cap
    EXPECT_NEAR(inst.anim.channels[1].blend_in_s, 0.34f, 1e-6f);
    renderer::bind_clip(inst, m, 1, b, 0.0);           // dur 0.1 < cap
    EXPECT_NEAR(inst.anim.channels[1].blend_in_s, 0.075f, 1e-6f);
}

TEST(SetRestPose, SamplesOnceClearsChannelsAndSetsRest) {
    assets::Model m = three_bone_model();
    // Placement clip with rest_locals only (no tracks) — the standard BC shape.
    assets::AnimationClip place; place.name = "place"; place.duration_seconds = 1.0f;
    place.rest_locals["Bip01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23));
    place.rest_locals["Bip01 Head"] = m.skeleton.bones[1].local_transform;
    place.rest_locals["Bip01 Spine"] = m.skeleton.bones[2].local_transform;
    m.animations = {place, clip_tracking({"Bip01 Head"})};

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::bind_clip(inst, m, 1, {}, 0.0);           // pre-existing gesture
    renderer::set_rest_pose(inst, m, 0, /*at_start=*/false);

    EXPECT_TRUE(inst.anim.has_rest);
    ASSERT_EQ(inst.anim.rest_locals.size(), 3u);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(inst.anim.rest_locals[0][3]), glm::vec3(33, -104, 23), 1e-4f)));
    for (const auto& ch : inst.anim.channels)
        EXPECT_EQ(ch.clip_index, -1) << "set_rest_pose must clear all channels";
    EXPECT_TRUE(inst.anim.dirty);

    // restore semantics: clear_channels after a new bind falls back to rest.
    renderer::bind_clip(inst, m, 1, {}, 2.0);
    EXPECT_EQ(inst.anim.channels[1].clip_index, 1);
    renderer::clear_channels(inst);
    for (const auto& ch : inst.anim.channels) EXPECT_EQ(ch.clip_index, -1);
    EXPECT_TRUE(inst.anim.has_rest) << "clear_channels must keep the rest pose";
}
