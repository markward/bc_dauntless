#include <gtest/gtest.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <string>
#include <unordered_map>

#include <assets/model.h>
#include <assets/model_compose.h>

// SP3 node-posing: apply_pose_to_nodes overwrites the local_transform of every
// body node whose name matches a placement-pose entry (the placement NIF's rest
// node skeleton), leaving non-matching nodes at their bind transform. This is
// the CPU core of the rigid-body officer pose (no GL, no palette, no
// inverse-bind, no keyframe sampling).

namespace {

assets::Model make_two_node_model() {
    assets::Model m;
    assets::Node head;
    head.name = "Bip01 Head";
    head.local_transform = glm::mat4(1.0f);  // bind = identity
    assets::Node spine;
    spine.name = "Bip01 Spine";
    // Distinct bind so we can prove a non-matching node is untouched.
    spine.local_transform = glm::translate(glm::mat4(1.0f),
                                           glm::vec3(9.0f, 9.0f, 9.0f));
    m.nodes.push_back(head);
    m.nodes.push_back(spine);
    m.root_node = 0;
    m.skeleton.bones.resize(2);
    m.skeleton.root_bone_index = 0;
    return m;
}

}  // namespace

TEST(ApplyPoseToNodes, OverwritesMatchingNodeLeavesOthersAtBind) {
    assets::Model model = make_two_node_model();
    const glm::mat4 spine_bind = model.nodes[1].local_transform;

    const glm::mat4 posed_head =
        glm::translate(glm::mat4(1.0f), glm::vec3(1.0f, 2.0f, 3.0f));
    std::unordered_map<std::string, glm::mat4> pose{{"Bip01 Head", posed_head}};

    assets::apply_pose_to_nodes(model, pose);

    // The matched "Bip01 Head" node now carries the placement rest local.
    EXPECT_EQ(model.nodes[0].local_transform, posed_head);
    // The non-matching "Bip01 Spine" node is unchanged from its bind.
    EXPECT_EQ(model.nodes[1].local_transform, spine_bind);
}

TEST(ApplyPoseToNodes, SkeletonCanBeClearedAfterPosing) {
    assets::Model model = make_two_node_model();
    std::unordered_map<std::string, glm::mat4> pose{
        {"Bip01 Head", glm::translate(glm::mat4(1.0f), glm::vec3(5, 0, 0))}};

    assets::apply_pose_to_nodes(model, pose);

    model.skeleton.bones.clear();
    model.skeleton.root_bone_index = -1;

    EXPECT_TRUE(model.skeleton.bones.empty());
    EXPECT_EQ(model.skeleton.root_bone_index, -1);
    EXPECT_FLOAT_EQ(model.nodes[0].local_transform[3][0], 5.0f);
}

TEST(ApplyPoseToNodes, NoMatchingNodesLeavesModelUntouched) {
    assets::Model model = make_two_node_model();
    const glm::mat4 head_bind = model.nodes[0].local_transform;
    const glm::mat4 spine_bind = model.nodes[1].local_transform;

    std::unordered_map<std::string, glm::mat4> pose{
        {"Bip01 Nonexistent", glm::translate(glm::mat4(1.0f), glm::vec3(7))}};

    assets::apply_pose_to_nodes(model, pose);

    EXPECT_EQ(model.nodes[0].local_transform, head_bind);
    EXPECT_EQ(model.nodes[1].local_transform, spine_bind);
}
