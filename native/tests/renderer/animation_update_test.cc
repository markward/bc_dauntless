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

    // A later call must NOT rebuild a settled, non-looping instance: palette
    // identical and still settled.
    renderer::update_animations(world, lookup, /*now=*/300.0);
    EXPECT_TRUE(world.get(id)->animation.settled);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);
}
