// native/tests/scenegraph/render_space_test.cc
//
// The floating render origin. Every instance keeps its translation in DOUBLE
// (Instance::world_translation_d) beside a float rotation·scale
// (Instance::world_linear); once per frame World::resolve_render_space
// subtracts the render origin IN DOUBLE and only then narrows to the float
// `world` every pass reads. Space pass only — the bridge and comm sets are
// their own little worlds and never move with the origin.
#include <gtest/gtest.h>

#include <scenegraph/world.h>

#include <glm/glm.hpp>

namespace {

glm::vec3 translation_of(const scenegraph::Instance& inst) {
    return glm::vec3(inst.world[3]);
}

TEST(RenderSpace, SpaceInstanceNarrowsOnlyAfterTheOriginIsSubtracted) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    w.set_world_transform_d(id, glm::mat3(1.0f), glm::dvec3(1e6, 0.0, 0.0));
    w.resolve_render_space(glm::dvec3(1e6 - 50.0, 0.0, 0.0));
    const auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_EQ(translation_of(*inst), glm::vec3(50.0f, 0.0f, 0.0f));
    EXPECT_EQ(inst->world[3][3], 1.0f);
}

TEST(RenderSpace, SubPrecisionOffsetSurvivesTheSubtraction) {
    // 1e6 + 0.3 is NOT a float (ulp 0.0625 at 1e6); subtracting in double
    // first keeps the 0.3 the float path would have rounded away.
    scenegraph::World w;
    auto id = w.create_instance(1);
    w.set_world_transform_d(id, glm::mat3(1.0f), glm::dvec3(1e6 + 0.3, 0.0, 0.0));
    w.resolve_render_space(glm::dvec3(1e6, 0.0, 0.0));
    EXPECT_EQ(translation_of(*w.get(id)).x, static_cast<float>(0.3));
}

TEST(RenderSpace, LinearPartIsCopiedThroughUntouched) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    const glm::mat3 lin(0.1f, 0.2f, 0.3f,
                        0.4f, 0.5f, 0.6f,
                        0.7f, 0.8f, 0.9f);
    w.set_world_transform_d(id, lin, glm::dvec3(1e6, 2.0, 3.0));
    w.resolve_render_space(glm::dvec3(1e6, 0.0, 0.0));
    const auto* inst = w.get(id);
    EXPECT_EQ(glm::mat3(inst->world), lin);
    EXPECT_EQ(inst->world[0][3], 0.0f);
    EXPECT_EQ(inst->world[1][3], 0.0f);
    EXPECT_EQ(inst->world[2][3], 0.0f);
}

TEST(RenderSpace, BridgeAndCommInstancesIgnoreTheOrigin) {
    scenegraph::World w;
    auto bridge = w.create_instance(1);
    auto comm = w.create_instance(2);
    w.set_pass(bridge, scenegraph::Pass::Bridge);
    w.set_pass(comm, scenegraph::Pass::Comm);
    w.set_world_transform_d(bridge, glm::mat3(1.0f), glm::dvec3(3.0, 4.0, 5.0));
    w.set_world_transform_d(comm, glm::mat3(1.0f), glm::dvec3(3.0, 4.0, 5.0));
    for (const glm::dvec3 origin : {glm::dvec3(0.0), glm::dvec3(1e6, -2e5, 7.0)}) {
        w.resolve_render_space(origin);
        EXPECT_EQ(translation_of(*w.get(bridge)), glm::vec3(3.0f, 4.0f, 5.0f));
        EXPECT_EQ(translation_of(*w.get(comm)), glm::vec3(3.0f, 4.0f, 5.0f));
    }
}

TEST(RenderSpace, ResolveIsIdempotentForAnUnchangedOrigin) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    w.set_world_transform_d(id, glm::mat3(2.0f), glm::dvec3(1e6 + 0.3, -3e5, 7.5));
    const glm::dvec3 origin(999'950.0, -299'990.0, 0.0);
    w.resolve_render_space(origin);
    const glm::mat4 once = w.get(id)->world;
    w.resolve_render_space(origin);
    w.resolve_render_space(origin);
    EXPECT_EQ(w.get(id)->world, once);
}

TEST(RenderSpace, APushBetweenFramesLandsInTheLastResolvedRenderSpace) {
    // Mesh queries and the like read inst->world between frames; a push must
    // not leave it in a different space from every other instance until the
    // next resolve.
    scenegraph::World w;
    w.resolve_render_space(glm::dvec3(1000.0, 0.0, 0.0));
    auto id = w.create_instance(1);
    w.set_world_transform_d(id, glm::mat3(1.0f), glm::dvec3(1010.0, 0.0, 0.0));
    EXPECT_EQ(translation_of(*w.get(id)), glm::vec3(10.0f, 0.0f, 0.0f));
}

TEST(RenderSpace, FloatPushKeepsItsMeaningAtAZeroOrigin) {
    // Every pre-existing set_world_transform(mat4) caller: with the origin at
    // zero the float matrix it pushed is exactly the matrix it reads back.
    scenegraph::World w;
    auto id = w.create_instance(1);
    glm::mat4 m(1.0f);
    m[0] = glm::vec4(0.0f, 2.0f, 0.0f, 0.0f);
    m[1] = glm::vec4(-2.0f, 0.0f, 0.0f, 0.0f);
    m[2] = glm::vec4(0.0f, 0.0f, 2.0f, 0.0f);
    m[3] = glm::vec4(123.25f, -4.5f, 6.0f, 1.0f);
    w.set_world_transform(id, m);
    EXPECT_EQ(w.get(id)->world, m);
    w.resolve_render_space(glm::dvec3(0.0));
    EXPECT_EQ(w.get(id)->world, m);
    EXPECT_EQ(w.get(id)->world_translation_d, glm::dvec3(123.25, -4.5, 6.0));
}

TEST(RenderSpace, APushUnbindsTheStoreSlot) {
    scenegraph::World w;
    auto id = w.create_instance(1);
    w.set_transform_slot(id, 3, 1, 1.0);
    w.set_world_transform_d(id, glm::mat3(1.0f), glm::dvec3(1.0, 2.0, 3.0));
    EXPECT_EQ(w.get(id)->xform_index, -1);
}

}  // namespace
