#include <gtest/gtest.h>
#include <renderer/node_anim.h>
#include <assets/model.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/matrix_decompose.hpp>

namespace {
// Two-node chain: root at origin, child translated +Y by 5.
assets::Model two_node() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node child; child.name = "console seat 01"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.nodes = {root, child};
    m.root_node = 0;
    return m;
}
}

TEST(ComposeNodeWorlds, NoOverridesMatchesStaticWalk) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), empty);
    ASSERT_EQ(w.size(), 2u);
    EXPECT_EQ(w[0], glm::mat4(1.0f));
    // child world = root * child local = translate(0,5,0)
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}

TEST(ComposeNodeWorlds, OverrideReplacesOnlyThatNodeLocal) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> ov;
    // Rotate the seat 90deg about Z in its local frame, keep its translation.
    glm::mat4 rot = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f), glm::vec3(0,0,1));
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(0,5,0)) * rot;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    EXPECT_EQ(w[0], glm::mat4(1.0f));                 // root untouched
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);             // translation preserved
    // local +X (1,0,0) rotated 90deg about Z -> +Y
    glm::vec3 col0 = glm::normalize(glm::vec3(w[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-4f);
}

TEST(ComposeNodeWorlds, InstanceWorldPremultiplies) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    glm::mat4 iw = glm::translate(glm::mat4(1.0f), glm::vec3(100,0,0));
    auto w = renderer::compose_node_worlds(m, iw, empty);
    EXPECT_NEAR(w[0][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}
