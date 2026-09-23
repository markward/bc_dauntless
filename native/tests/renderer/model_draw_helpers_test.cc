#include <gtest/gtest.h>

#include <renderer/node_anim.h>
#include <assets/model.h>

#include <glm/gtc/matrix_transform.hpp>

#include <unordered_map>

namespace {

// Root -> child. The child carries a translation so a moved child is
// distinguishable from an unmoved one by inspection.
assets::Model two_node_model() {
    assets::Model m;
    m.nodes.resize(2);
    m.root_node = 0;
    m.nodes[0].parent_index = -1;
    m.nodes[0].local_transform = glm::mat4(1.0f);
    m.nodes[1].parent_index = 0;
    m.nodes[1].local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(1.0f, 0.0f, 0.0f));
    return m;
}

}  // namespace

TEST(ModelDrawHelpers, AnEmptyOverrideMapReproducesTheStaticWalk) {
    const assets::Model m = two_node_model();
    const glm::mat4 world = glm::translate(glm::mat4(1.0f),
                                           glm::vec3(0.0f, 5.0f, 0.0f));
    const std::unordered_map<int, glm::mat4> none;

    const auto composed = renderer::compose_node_worlds(m, world, none);

    // The hand-rolled walk this replaces.
    std::vector<glm::mat4> expected(m.nodes.size(), glm::mat4(1.0f));
    expected[m.root_node] = world * m.nodes[m.root_node].local_transform;
    for (std::size_t i = 0; i < m.nodes.size(); ++i)
        if (m.nodes[i].parent_index >= 0)
            expected[i] = expected[m.nodes[i].parent_index] *
                          m.nodes[i].local_transform;

    ASSERT_EQ(composed.size(), expected.size());
    for (std::size_t i = 0; i < composed.size(); ++i)
        EXPECT_EQ(composed[i], expected[i]) << "node " << i;
}

TEST(ModelDrawHelpers, AnOverriddenChildMovesAndTheRootDoesNot) {
    const assets::Model m = two_node_model();
    const glm::mat4 world(1.0f);
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, 9.0f));

    const auto composed = renderer::compose_node_worlds(m, world, ov);

    EXPECT_EQ(composed[0], glm::mat4(1.0f));
    EXPECT_EQ(composed[1][3].z, 9.0f) << "the override must replace the local";
    EXPECT_EQ(composed[1][3].x, 0.0f) << "and REPLACE it, not compose with it";
}

TEST(ModelDrawHelpers, AZeroMatrixCollapsesTheSubtreeSoASeveredPartVanishes) {
    // set_instance_node_hidden writes mat4(0) as a node's local. That is how a
    // severed wing disappears -- every vertex in its subtree lands on the
    // origin, so its triangles have zero area. A pass honouring overrides
    // therefore needs NO separate visibility test.
    const assets::Model m = two_node_model();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::mat4(0.0f);

    const auto composed = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);

    EXPECT_EQ(composed[1], glm::mat4(0.0f));
}
