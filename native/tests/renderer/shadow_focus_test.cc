#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <scenegraph/world.h>
#include "assets/model.h"
#include "renderer/frame.h"

namespace {

// One node, one mesh: two points at +-h on X, so the model AABB has
// half-extents (h, 0, 0) and a bounding radius of h.
assets::Model bar_model(float h) {
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0},
    });
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = {-h, 0, 0}, .normal = {0, 0, 1}});
    cpu.vertices.push_back({.position = { h, 0, 0}, .normal = {0, 0, 1}});
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return m;
}

scenegraph::ModelHandle handle_of(const assets::Model& m) {
    return reinterpret_cast<scenegraph::ModelHandle>(&m);
}

renderer::FrameSubmitter::ModelLookup lookup_for() {
    return [](unsigned long long h) {
        return reinterpret_cast<const assets::Model*>(h);
    };
}

scenegraph::InstanceId hull_at(scenegraph::World& w, const assets::Model& m,
                               glm::vec3 pos, float scale) {
    auto id = w.create_instance(handle_of(m));
    w.set_world_transform(id, glm::scale(glm::translate(glm::mat4(1.0f), pos),
                                         glm::vec3(scale)));
    w.set_rim_eligible(id, true);
    return id;
}

class ShadowFocusTest : public ::testing::Test {
protected:
    void SetUp() override { renderer::reset_model_radius_cache(); }
    void TearDown() override { renderer::reset_model_radius_cache(); }
};

}  // namespace

TEST_F(ShadowFocusTest, PicksTheNearestHullAndScalesItsRadius) {
    assets::Model bar = bar_model(3.0f);
    scenegraph::World w;
    hull_at(w, bar, {50, 0, 0}, 1.0f);
    auto near = hull_at(w, bar, {10, 0, 0}, 2.0f);
    // Nearer still, but not a hull (planets etc. are not rim-eligible).
    auto planet = w.create_instance(handle_of(bar));
    w.set_world_transform(planet, glm::translate(glm::mat4(1.0f), {1, 0, 0}));

    renderer::ShadowFocus f = renderer::pick_shadow_focus(w, {0, 0, 0}, lookup_for());
    ASSERT_NE(f.instance, nullptr);
    EXPECT_EQ(f.instance, w.get(near));
    EXPECT_FLOAT_EQ(f.radius_gu, 6.0f);   // radius 3 x scale 2
}

TEST_F(ShadowFocusTest, NoHullMeansNoFocus) {
    assets::Model bar = bar_model(3.0f);
    scenegraph::World w;
    auto hidden = hull_at(w, bar, {10, 0, 0}, 1.0f);
    w.set_visible(hidden, false);

    renderer::ShadowFocus f = renderer::pick_shadow_focus(w, {0, 0, 0}, lookup_for());
    EXPECT_EQ(f.instance, nullptr);
    EXPECT_FLOAT_EQ(f.radius_gu, 0.0f);
}

TEST_F(ShadowFocusTest, RadiusIsCachedPerModelNotRecomputedEachFrame) {
    // The focus search ran every frame; walking every vertex of each hull
    // it met cost ~3 ms in a 17-ship fight (Debug). The radius now comes
    // from the per-model cache, so a later edit to the CPU mesh is not seen
    // until the cache is reset (the host resets it when models reload).
    assets::Model bar = bar_model(3.0f);
    scenegraph::World w;
    hull_at(w, bar, {10, 0, 0}, 1.0f);
    EXPECT_FLOAT_EQ(renderer::pick_shadow_focus(w, {0, 0, 0}, lookup_for()).radius_gu, 3.0f);

    assets::MeshCpu wider;
    wider.vertices.push_back({.position = {-9, 0, 0}, .normal = {0, 0, 1}});
    wider.vertices.push_back({.position = { 9, 0, 0}, .normal = {0, 0, 1}});
    bar.meshes[0].set_cpu_data(std::move(wider));
    EXPECT_FLOAT_EQ(renderer::pick_shadow_focus(w, {0, 0, 0}, lookup_for()).radius_gu, 3.0f);

    renderer::reset_model_radius_cache();
    EXPECT_FLOAT_EQ(renderer::pick_shadow_focus(w, {0, 0, 0}, lookup_for()).radius_gu, 9.0f);
}
