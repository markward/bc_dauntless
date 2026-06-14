#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/animation_update.h>

namespace {
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
