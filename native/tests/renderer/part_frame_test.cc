// A carve must land on the part it struck, not on the hull beneath where
// that part sits at rest. The damage field is baked rest-pose and shared by
// every instance of the hull, so the query point is pulled back into the
// struck part's rest frame rather than the field being re-baked per pose.

#include <gtest/gtest.h>

#include <optional>
#include <unordered_map>

#include <glm/gtc/matrix_transform.hpp>

#include <assets/model.h>
#include <renderer/part_frame.h>

namespace {

// Root (no geometry) + a child holding one triangle around x = +10, so an
// override on the child is distinguishable from one on the root and the
// moved and rest positions are far apart.
assets::Model root_plus_movable_child() {
    assets::Model m;
    m.root_node = 0;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
    });
    m.nodes.push_back(assets::Node{
        .name = "wing", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f),
                                          glm::vec3(10.0f, 0.0f, 0.0f)),
        .meshes = {0},
    });
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = glm::vec3(-1, -1, -1)});
    cpu.vertices.push_back({.position = glm::vec3(1, -1, 1)});
    cpu.vertices.push_back({.position = glm::vec3(0, 1, 0)});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return m;
}

}  // namespace

TEST(PartFrame, NoOverridesClaimsNothing) {
    // The overwhelmingly common case and the one that must not change: with
    // no overrides every carve keeps its body point untouched.
    auto m = root_plus_movable_child();
    const std::unordered_map<int, glm::mat4> none;
    EXPECT_FALSE(renderer::rest_from_posed_at(m, none, glm::vec3(10, 0, 0))
                     .has_value());
}

TEST(PartFrame, APointOnTheMovedPartYieldsItsRestFrame) {
    // THE POINT. The wing is drawn at x = -10; a carve there must come back
    // with the transform that puts it at x = +10, where the field has it.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));

    auto rest = renderer::rest_from_posed_at(m, ov, glm::vec3(-10, 0, 0));
    ASSERT_TRUE(rest.has_value());
    const glm::vec3 p(*rest * glm::vec4(-10.0f, 0.0f, 0.0f, 1.0f));
    EXPECT_NEAR(p.x, 10.0f, 1e-4f);
    EXPECT_NEAR(p.y, 0.0f, 1e-4f);
    EXPECT_NEAR(p.z, 0.0f, 1e-4f);
}

TEST(PartFrame, APointOffEveryMovedPartClaimsNothing) {
    // The other half, and the one a weak test would miss: a hit on the body
    // while a wing is raised must not be dragged into the wing's frame.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));
    EXPECT_FALSE(renderer::rest_from_posed_at(m, ov, glm::vec3(0, 0, 0))
                     .has_value());
}

TEST(PartFrame, ASeveredPartClaimsNothing) {
    // A hidden part is the ZERO matrix (set_instance_node_hidden), which is
    // singular — inverting it produces NaNs that would poison the field.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::mat4(0.0f);
    for (float x : {10.0f, 0.0f, -10.0f}) {
        EXPECT_FALSE(
            renderer::rest_from_posed_at(m, ov, glm::vec3(x, 0, 0)).has_value())
            << "severed part claimed a carve at x = " << x;
    }
}

TEST(PartFrame, AMovedParentClaimsItsChildsMesh) {
    // The trap plan 2 hit LIVE: find_parent_node_index attaches a mesh to its
    // immediate NiNode parent (__NDL_MultiMtl_Node), NOT to the part node an
    // override names. A real BC hull is three levels, not two, so a node's
    // geometry includes its DESCENDANTS'.
    auto m = root_plus_movable_child();
    m.nodes[1].meshes.clear();               // geometry hangs off the child
    m.nodes.push_back(assets::Node{
        .name = "__NDL_MultiMtl_Node", .parent_index = 1,
        .local_transform = glm::translate(glm::mat4(1.0f),
                                          glm::vec3(0.0f, 0.0f, 5.0f)),
        .meshes = {0},
    });
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));

    // The grandchild mesh sits around (10, 0, 5) at rest, (-10, 0, 5) posed.
    auto rest = renderer::rest_from_posed_at(m, ov, glm::vec3(-10, 0, 5));
    ASSERT_TRUE(rest.has_value())
        << "an override on a part must claim its CHILDREN's geometry too";
    const glm::vec3 p(*rest * glm::vec4(-10.0f, 0.0f, 5.0f, 1.0f));
    EXPECT_NEAR(p.x, 10.0f, 1e-4f);
    EXPECT_NEAR(p.z, 5.0f, 1e-4f);
}
