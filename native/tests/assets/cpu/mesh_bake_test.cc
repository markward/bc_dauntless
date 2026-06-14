// native/tests/assets/cpu/mesh_bake_test.cc
//
// CPU regression guard for the skinned-mesh "explosion" bug. BC character
// bodies are mostly RIGID shapes parented to bone nodes and rendered through
// the skinned program. Before the model-space bake, such a part was drawn as
//     u_model(=world·node_chain) · palette[B] · v_local
// where palette[B] = world_pose(B)·inverse(world_bind(B)). At bind pose the
// palette is identity so it collapsed correctly, hiding the bug; under a real
// pose the leftover bind transform flung each part away.
//
// The fix bakes node_chain INTO the vertices (model space) and draws with
// u_model = inst.world only, so the part poses as
//     inst.world · palette[B] · v_baked == inst.world · world_pose(B) · v_local
// This test reproduces that pipeline on the CPU (no GL) and asserts the baked,
// posed vertex lands at the expected posed position — NOT exploded.

#include <gtest/gtest.h>

#include "mesh_bake.h"

#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/skeleton.h>

#include <glm/gtc/matrix_transform.hpp>

#include <vector>

namespace {

using assets::detail::bake_mesh_to_model_space;
using assets::detail::compute_local_world_per_node;

// world_bind(b): compose bone local transforms from root down to b.
glm::mat4 world_bind(const assets::Skeleton& sk, int b) {
    std::vector<int> chain;
    for (int i = b; i != -1; i = sk.bones[i].parent_index) chain.push_back(i);
    glm::mat4 w(1.0f);
    for (auto it = chain.rbegin(); it != chain.rend(); ++it)
        w = w * sk.bones[*it].local_transform;
    return w;
}

// Mirror renderer::build_bone_palette for a single bone with a supplied pose:
// palette[b] = world_pose(b) * inverse_bind_pose(b).
glm::mat4 palette_entry(const assets::Skeleton& sk,
                        const std::vector<glm::mat4>& pose_local, int b) {
    std::vector<int> chain;
    for (int i = b; i != -1; i = sk.bones[i].parent_index) chain.push_back(i);
    glm::mat4 world_pose(1.0f);
    for (auto it = chain.rbegin(); it != chain.rend(); ++it)
        world_pose = world_pose * pose_local[*it];
    return world_pose * sk.bones[b].inverse_bind_pose;
}

// Two bones, two matching nodes: Root → Child. The "rigid part" mesh is
// attached to the Child node (node index 1), which shares Child bone's
// transform, so local_world_per_node[1] == world_bind(child).
struct Rig {
    assets::Skeleton sk;
    std::vector<assets::Node> nodes;
    int child_bone = 1;
    int child_node = 1;
};

Rig make_rig() {
    Rig r;
    const glm::mat4 root_local =
        glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    const glm::mat4 child_local =
        glm::rotate(glm::mat4(1.0f), glm::radians(30.0f), glm::vec3(0, 0, 1)) *
        glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));

    assets::Bone root; root.parent_index = -1; root.local_transform = root_local;
    assets::Bone child; child.parent_index = 0; child.local_transform = child_local;
    r.sk.bones = {root, child};
    r.sk.root_bone_index = 0;
    r.sk.bones[0].inverse_bind_pose = glm::inverse(world_bind(r.sk, 0));
    r.sk.bones[1].inverse_bind_pose = glm::inverse(world_bind(r.sk, 1));

    assets::Node nroot; nroot.parent_index = -1; nroot.local_transform = root_local;
    assets::Node nchild; nchild.parent_index = 0; nchild.local_transform = child_local;
    r.nodes = {nroot, nchild};
    return r;
}

}  // namespace

// local_world_per_node for the child node must equal world_bind(child bone):
// the precondition that makes the bake cancel cleanly with inverse_bind.
TEST(MeshBake, NodeChainMatchesBoneBind) {
    Rig r = make_rig();
    auto lwpn = compute_local_world_per_node(r.nodes, /*root_node=*/0);
    ASSERT_EQ(lwpn.size(), 2u);
    const glm::mat4 wb = world_bind(r.sk, r.child_bone);
    for (int c = 0; c < 4; ++c)
        for (int row = 0; row < 4; ++row)
            EXPECT_NEAR(lwpn[r.child_node][c][row], wb[c][row], 1e-4f);
}

// THE EXPLOSION GUARD: bake a rigid part to model space, then pose it via the
// bone palette and assert it lands at inst.world · world_pose(child) · v_local,
// NOT at the exploded position the old per-node u_model produced.
TEST(MeshBake, BakedRigidPartPosesWithoutExploding) {
    Rig r = make_rig();

    // A rigid part: one vertex expressed in the CHILD node's local frame.
    const glm::vec3 v_local(1.0f, 0.0f, 0.0f);
    assets::MeshCpu cpu;
    cpu.node_index = r.child_node;
    cpu.vertices.push_back(assets::MeshCpu::Vertex{});
    cpu.vertices[0].position = v_local;
    cpu.vertices[0].normal = glm::vec3(0, 1, 0);

    // Bake: transform verts into model space by the node chain.
    auto lwpn = compute_local_world_per_node(r.nodes, /*root_node=*/0);
    bake_mesh_to_model_space(cpu, lwpn[r.child_node]);

    // A non-trivial pose: rotate the child bone an extra 40° about Z in its
    // local frame (the kind of thing a real animation keyframe does).
    std::vector<glm::mat4> pose_local = {
        r.sk.bones[0].local_transform,  // root unchanged
        glm::rotate(glm::mat4(1.0f), glm::radians(40.0f), glm::vec3(0, 0, 1)) *
            r.sk.bones[1].local_transform,
    };
    const glm::mat4 inst_world =
        glm::translate(glm::mat4(1.0f), glm::vec3(100, 0, 0));

    // Renderer math: final = inst.world · palette[child] · v_baked.
    const glm::mat4 pal = palette_entry(r.sk, pose_local, r.child_bone);
    const glm::vec4 got =
        inst_world * pal * glm::vec4(cpu.vertices[0].position, 1.0f);

    // Expected: the part rigidly follows the child bone's POSED world frame:
    //   inst.world · world_pose(child) · v_local.
    glm::mat4 world_pose_child(1.0f);
    {
        std::vector<int> chain;
        for (int i = r.child_bone; i != -1; i = r.sk.bones[i].parent_index)
            chain.push_back(i);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            world_pose_child = world_pose_child * pose_local[*it];
    }
    const glm::vec4 expected =
        inst_world * world_pose_child * glm::vec4(v_local, 1.0f);

    EXPECT_NEAR(got.x, expected.x, 1e-3f);
    EXPECT_NEAR(got.y, expected.y, 1e-3f);
    EXPECT_NEAR(got.z, expected.z, 1e-3f);

    // And explicitly NOT exploded: the legacy per-node u_model path would have
    // produced inst.world · node_chain · palette · v_local, which differs.
    const glm::vec4 exploded =
        inst_world * lwpn[r.child_node] * pal *
        glm::vec4(cpu.vertices[0].position, 1.0f);
    const float err = glm::length(glm::vec3(exploded - expected));
    EXPECT_GT(err, 1.0f)
        << "legacy per-node path should diverge from the correct pose; if this "
           "is ~0 the pose is too trivial to be a meaningful guard.";
}
