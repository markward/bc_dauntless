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

// Root + a child holding a thin NEEDLE-shaped wing attached at x = +10:
// local vertices span x in [-5,5], y in [-0.2,0.2], z = 0. Its REST world
// AABB is tight: x in [5,15], y in [-0.2,0.2]. Rotating it about its own
// attach point sweeps that tight box into a much bigger, roughly square
// posed AABB -- exactly the shape Finding 1's fuselage-hit scenario needs.
assets::Model root_plus_rotated_needle_wing() {
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
    cpu.vertices.push_back({.position = glm::vec3(-5.0f, 0.0f, 0.0f)});
    cpu.vertices.push_back({.position = glm::vec3(5.0f, 0.2f, 0.0f)});
    cpu.vertices.push_back({.position = glm::vec3(5.0f, -0.2f, 0.0f)});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return m;
}

// Two SIBLING overridden nodes both drawn to the SAME posed location (the
// port/starboard wing roots overlapping near the spine, from Finding 2).
// wingA's rest box is big (volume 1000, half-extent 5 around rest x = 0);
// wingB's is small (volume 1, half-extent 0.5 around rest x = 1). Both
// override to translate(50,0,0), so both claim body_point (50,0,0) once
// pulled back -- exercising the tie-break rule rather than relying on
// unordered_map iteration order to happen to pick one.
assets::Model root_plus_two_overlapping_wings() {
    assets::Model m;
    m.root_node = 0;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
    });
    m.nodes.push_back(assets::Node{
        .name = "wingA_big", .parent_index = 0,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0},
    });
    m.nodes.push_back(assets::Node{
        .name = "wingB_small", .parent_index = 0,
        .local_transform = glm::translate(glm::mat4(1.0f),
                                          glm::vec3(1.0f, 0.0f, 0.0f)),
        .meshes = {1},
    });

    assets::MeshCpu big;
    big.vertices.push_back({.position = glm::vec3(-5.0f, -5.0f, -5.0f)});
    big.vertices.push_back({.position = glm::vec3(5.0f, -5.0f, 5.0f)});
    big.vertices.push_back({.position = glm::vec3(0.0f, 5.0f, 0.0f)});
    big.indices = {0u, 1u, 2u};
    assets::Mesh big_mesh;
    big_mesh.set_cpu_data(std::move(big));
    m.meshes.push_back(std::move(big_mesh));

    assets::MeshCpu small;
    small.vertices.push_back({.position = glm::vec3(-0.5f, -0.5f, -0.5f)});
    small.vertices.push_back({.position = glm::vec3(0.5f, -0.5f, 0.5f)});
    small.vertices.push_back({.position = glm::vec3(0.0f, 0.5f, 0.0f)});
    small.indices = {0u, 1u, 2u};
    assets::Mesh small_mesh;
    small_mesh.set_cpu_data(std::move(small));
    m.meshes.push_back(std::move(small_mesh));

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

TEST(PartFrame, APointInsideTheRotatedBoxButNotOnThePartClaimsNothing) {
    // Finding 1: containment used to be tested against the POSED subtree
    // AABB, which for a ROTATED slab is far bigger than the slab itself.
    // Build the override exactly as set_instance_node_rotation does:
    // T(pivot) . R(axis, theta) . T(-pivot) . local_transform, hinging the
    // needle wing at its own attach point (10,0,0) by 45 degrees about Z.
    //
    // Hand-verified: rest AABB is x in [5,15], y in [-0.2,0.2], z = 0.
    // Posed AABB (rotated vertices, +10 on x) works out to roughly
    // x in [6.46,13.68], y in [-3.54,3.68] -- the y-extent balloons from
    // 0.4 wide to over 7 wide. (13,-3,0) sits inside that posed box (it is
    // near the "other corner", nowhere close to the actual diagonal sliver,
    // which is the fuselage-hit case). Pulling it back through to_rest
    // lands at approximately (10,-4.24,0): x is inside [5,15], but
    // y = -4.24 is far outside the tight rest y-range of [-0.2,0.2], so the
    // fixed rest-box test correctly rejects it. A posed-box test would have
    // wrongly claimed it for the wing.
    auto m = root_plus_rotated_needle_wing();
    std::unordered_map<int, glm::mat4> ov;
    const glm::vec3 pivot(10.0f, 0.0f, 0.0f);
    const glm::vec3 axis(0.0f, 0.0f, 1.0f);
    const float theta = glm::radians(45.0f);
    ov[1] = glm::translate(glm::mat4(1.0f), pivot) *
            glm::rotate(glm::mat4(1.0f), theta, axis) *
            glm::translate(glm::mat4(1.0f), -pivot) *
            m.nodes[1].local_transform;

    EXPECT_FALSE(
        renderer::rest_from_posed_at(m, ov, glm::vec3(13.0f, -3.0f, 0.0f))
            .has_value())
        << "a point inside the rotated part's posed bounding box, but off "
           "its actual rest geometry, must not be claimed";
}

TEST(PartFrame, OverlappingOverridesPickSmallestRestBoxDeterministically) {
    // Finding 2: iteration order over `overrides` (an unordered_map) must
    // not decide the winner when two overridden nodes both claim a point --
    // e.g. port and starboard wing roots drawn to the same location near
    // the spine. Both wingA (rest-box volume 1000) and wingB (rest-box
    // volume 1) are overridden to the SAME posed location; the stated rule
    // (header) is smallest rest-box volume wins, so wingB must win
    // regardless of which order the map happens to iterate the two entries.
    auto m = root_plus_two_overlapping_wings();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(50.0f, 0.0f, 0.0f));  // wingA
    ov[2] = glm::translate(glm::mat4(1.0f), glm::vec3(50.0f, 0.0f, 0.0f));  // wingB

    auto rest = renderer::rest_from_posed_at(m, ov, glm::vec3(50.0f, 0.0f, 0.0f));
    ASSERT_TRUE(rest.has_value());
    const glm::vec3 p(*rest * glm::vec4(50.0f, 0.0f, 0.0f, 1.0f));
    // wingB's rest is x = 1; wingA's is x = 0. The smaller box (wingB) must
    // win no matter which order the unordered_map iterates the two entries.
    EXPECT_NEAR(p.x, 1.0f, 1e-4f)
        << "the SMALLER overlapping rest box must win, not hash order";
}
