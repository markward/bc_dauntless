#include <gtest/gtest.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>

#include <assets/animation.h>
#include <assets/model.h>
#include <assets/model_compose.h>

// SP3 node-posing: apply_pose_to_nodes overwrites the local_transform of every
// node whose name matches a clip track's target, leaving non-matching nodes at
// their bind transform. This is the CPU core of the rigid-body officer pose
// (no GL, no palette, no inverse-bind).

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
    // A skeleton present so we can also prove it can be cleared by the caller.
    m.skeleton.bones.resize(2);
    m.skeleton.root_bone_index = 0;
    return m;
}

assets::AnimationClip make_clip_translating_head(const glm::vec3& target) {
    assets::AnimationClip clip;
    clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr;
    tr.target_node_name = "Bip01 Head";
    // Single translation key at t=duration -> sampled value is exactly target.
    tr.translation.push_back({1.0f, target});
    clip.tracks.push_back(std::move(tr));
    return clip;
}

}  // namespace

TEST(ApplyPoseToNodes, OverwritesMatchingNodeLeavesOthersAtBind) {
    assets::Model model = make_two_node_model();
    const glm::vec3 posed_head_t(1.0f, 2.0f, 3.0f);
    const assets::AnimationClip clip = make_clip_translating_head(posed_head_t);

    const glm::mat4 spine_bind = model.nodes[1].local_transform;

    assets::apply_pose_to_nodes(model, clip, clip.duration_seconds);

    // The matched "Bip01 Head" node's local_transform now carries the sampled
    // translation (rotation identity, scale 1 -> a pure translation matrix).
    const glm::vec3 head_t = glm::vec3(model.nodes[0].local_transform[3]);
    EXPECT_FLOAT_EQ(head_t.x, posed_head_t.x);
    EXPECT_FLOAT_EQ(head_t.y, posed_head_t.y);
    EXPECT_FLOAT_EQ(head_t.z, posed_head_t.z);
    // Upper-left 3x3 is identity (no rotation/scale in this clip).
    EXPECT_FLOAT_EQ(model.nodes[0].local_transform[0][0], 1.0f);
    EXPECT_FLOAT_EQ(model.nodes[0].local_transform[1][1], 1.0f);
    EXPECT_FLOAT_EQ(model.nodes[0].local_transform[2][2], 1.0f);

    // The non-matching "Bip01 Spine" node is unchanged from its bind.
    EXPECT_EQ(model.nodes[1].local_transform, spine_bind);
}

TEST(ApplyPoseToNodes, SkeletonCanBeClearedAfterPosing) {
    assets::Model model = make_two_node_model();
    const assets::AnimationClip clip =
        make_clip_translating_head(glm::vec3(5.0f, 0.0f, 0.0f));

    assets::apply_pose_to_nodes(model, clip, clip.duration_seconds);

    // Clearing the skeleton is what routes the posed model to the STATIC bridge
    // walk (and away from the skinned sub-pass). Prove it leaves an empty,
    // sentinel-rooted skeleton with the posed nodes intact.
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

    // Track targets a name no node carries.
    assets::AnimationClip clip;
    clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr;
    tr.target_node_name = "Bip01 Nonexistent";
    tr.translation.push_back({1.0f, glm::vec3(7.0f)});
    clip.tracks.push_back(std::move(tr));

    assets::apply_pose_to_nodes(model, clip, clip.duration_seconds);

    EXPECT_EQ(model.nodes[0].local_transform, head_bind);
    EXPECT_EQ(model.nodes[1].local_transform, spine_bind);
}
