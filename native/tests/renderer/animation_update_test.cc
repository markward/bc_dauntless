#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <glm/gtx/quaternion.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/animation_update.h>

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
}

TEST(AnimationUpdate, PlayOnceHoldRebuildsThenSettles) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;
    st.clip_index = 0; st.start_wall_time = 100.0; st.loop = false;
    world.set_animation(id, st);

    // Before the clip ends: palette rebuilt, not settled.
    renderer::update_animations(world, lookup, /*now=*/100.5);
    ASSERT_TRUE(world.get(id));
    EXPECT_FALSE(world.get(id)->animation.settled);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);

    // After duration: clamped to end, marked settled.
    renderer::update_animations(world, lookup, /*now=*/200.0);
    EXPECT_TRUE(world.get(id)->animation.settled);
    auto settled_palette = world.get(id)->bone_palette;
    ASSERT_EQ(settled_palette.size(), 2u);

    // Content check: palette[1] must apply the clip's 90deg-about-Z rotation of
    // j1, not just be right-sized. j1's world pose is root(identity) * j1.local
    // with the 90deg-Z rotation post-applied at j1; the skin matrix is
    //   world_pose(j1) * inverse_bind(j1).
    // Transform a known point and confirm it lands where the rotation predicts.
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 j1_world = j1_local * glm::mat4_cast(q90);
    glm::mat4 j1_inv_bind = glm::inverse(j1_local);
    glm::mat4 expect_skin = j1_world * j1_inv_bind;
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    glm::vec4 got = settled_palette[1] * probe;
    glm::vec4 want = expect_skin * probe;
    EXPECT_TRUE(glm::all(glm::epsilonEqual(got, want, 1e-4f)))
        << "palette[1] did not apply the 90deg-Z rotation: got ("
        << got.x << "," << got.y << "," << got.z << ") want ("
        << want.x << "," << want.y << "," << want.z << ")";

    // A later call must NOT rebuild a settled, non-looping instance: palette is
    // bit-identical (glm mat4 operator== is exact) and still settled. A palette
    // rebuilt every frame would still be size 2, so compare every matrix.
    renderer::update_animations(world, lookup, /*now=*/300.0);
    EXPECT_TRUE(world.get(id)->animation.settled);
    ASSERT_EQ(world.get(id)->bone_palette.size(), settled_palette.size());
    for (std::size_t b = 0; b < settled_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], settled_palette[b]);
}

TEST(AnimationUpdate, SampleAtEndHoldsEndFrameAndSettlesImmediately) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;
    st.clip_index = 0; st.start_wall_time = 100.0; st.loop = false;
    st.sample_at_end = true;
    world.set_animation(id, st);

    // Settles on the FIRST update, no play-through, even at t just past start.
    renderer::update_animations(world, lookup, /*now=*/100.01);
    ASSERT_TRUE(world.get(id));
    EXPECT_TRUE(world.get(id)->animation.settled);
    auto end_palette = world.get(id)->bone_palette;
    ASSERT_EQ(end_palette.size(), 2u);

    // Held palette equals the t=dur pose (clip's 90deg-Z key is constant).
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin = (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(end_palette[1] * probe,
                                           expect_skin * probe, 1e-4f)));

    // Freezes: a later call leaves the palette bit-identical.
    renderer::update_animations(world, lookup, /*now=*/500.0);
    for (std::size_t b = 0; b < end_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], end_palette[b]);
}

TEST(AnimationUpdate, SampleAtStartHoldsStartFrameAndSettles) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;
    st.clip_index = 0; st.start_wall_time = 100.0; st.loop = false;
    st.sample_at_start = true;
    world.set_animation(id, st);

    // A sample_at_start instance evaluates the clip at t=0 and settles on the
    // FIRST update, regardless of how far past start_wall_time we are.
    renderer::update_animations(world, lookup, /*now=*/100.5);
    ASSERT_TRUE(world.get(id));
    EXPECT_TRUE(world.get(id)->animation.settled);
    auto start_palette = world.get(id)->bone_palette;
    ASSERT_EQ(start_palette.size(), 2u);

    // The held palette must equal the t=0 pose. The clip's single 90deg-Z key is
    // constant across the clip, so t=0 has the same rotation; confirm palette[1]
    // applies it (i.e. the start frame is the clip pose, not bind pose / garbage).
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin = (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    glm::vec4 got = start_palette[1] * probe;
    glm::vec4 want = expect_skin * probe;
    EXPECT_TRUE(glm::all(glm::epsilonEqual(got, want, 1e-4f)));

    // And it freezes: a later call leaves the palette bit-identical.
    renderer::update_animations(world, lookup, /*now=*/500.0);
    ASSERT_EQ(world.get(id)->bone_palette.size(), start_palette.size());
    for (std::size_t b = 0; b < start_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], start_palette[b]);
}

TEST(AnimationUpdate, LayerOverRestKeepsRootAtStation) {
    // Verifies that a gesture clip played with layer_over_rest=true keeps the
    // root bone at the placement (rest) pose position, not at origin/bind.
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);

    // Set rest pose to clip[0] (the placement clip, holds last frame = station).
    scenegraph::Instance::AnimationState rest_st;
    rest_st.clip_index = 0;
    rest_st.loop = false;
    rest_st.sample_at_end = true;  // placement clips hold last frame
    rest_st.start_wall_time = 0.0;
    world.set_rest_pose(id, rest_st);

    // Play gesture clip[1] layered over the rest pose.
    scenegraph::Instance::AnimationState gesture_st;
    gesture_st.clip_index = 1;
    gesture_st.loop = false;
    gesture_st.layer_over_rest = true;
    gesture_st.start_wall_time = 0.0;
    world.set_animation(id, gesture_st);

    renderer::update_animations(world, lookup, /*now=*/0.5);
    ASSERT_TRUE(world.get(id));
    const auto& palette = world.get(id)->bone_palette;
    ASSERT_EQ(palette.size(), 2u);

    // palette[0] = world_pose(root) * inverse_bind(root).
    // Root's world_pose should be the station translation (33,-104,23), not origin.
    // inverse_bind(root) = identity, so palette[0] == station_translation.
    glm::vec4 probe(0.0f, 0.0f, 0.0f, 1.0f);
    glm::vec4 root_world = palette[0] * probe;
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(root_world), glm::vec3(33.0f, -104.0f, 23.0f), 1e-3f)))
        << "Root not at station: got (" << root_world.x << "," << root_world.y
        << "," << root_world.z << ") expected (33,-104,23)";
}

TEST(AnimationUpdate, LoopingLayeredIdleStaysAnchoredAndNeverSettles) {
    // Breathing: clip[1] played with loop=true + layer_over_rest=true must keep
    // the root at the placement station across cycling t, and never settle (it
    // loops forever until replaced).
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);

    scenegraph::Instance::AnimationState rest_st;
    rest_st.clip_index = 0;
    rest_st.sample_at_end = true;        // placement holds last frame = station
    world.set_rest_pose(id, rest_st);

    scenegraph::Instance::AnimationState idle_st;
    idle_st.clip_index = 1;
    idle_st.loop = true;
    idle_st.layer_over_rest = true;
    idle_st.start_wall_time = 0.0;
    world.set_animation(id, idle_st);

    auto root_world_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return glm::vec3(world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1));
    };

    // Sample within the first cycle and well past the clip duration (looped).
    glm::vec3 r1 = root_world_at(0.3);
    EXPECT_FALSE(world.get(id)->animation.settled);   // looping never settles
    glm::vec3 r2 = root_world_at(50.0);
    EXPECT_FALSE(world.get(id)->animation.settled);

    // Root stays at the station at BOTH times (the idle clip has no root track).
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r1, glm::vec3(33,-104,23), 1e-3f)));
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r2, glm::vec3(33,-104,23), 1e-3f)));
}
