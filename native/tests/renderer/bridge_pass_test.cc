// native/tests/renderer/bridge_pass_test.cc
//
// CPU-side test that BridgePass's instance walk only sees bridge-tagged
// instances. We cannot invoke BridgePass::render() here (it issues real GL
// calls); bridge_lighting_test.cc renders through it.
#include <gtest/gtest.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <scenegraph/world.h>
#include <scenegraph/instance.h>

namespace {

assets::Mesh make_stub_mesh(int material_index) {
    return assets::Mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0,
                        /*index_count=*/3, material_index, /*node_index=*/0);
}

}  // namespace

TEST(BridgePassPartitioning, SkipsNonBridgePassInstances) {
    assets::Model model;
    model.materials.push_back(assets::Material{});
    model.meshes.push_back(make_stub_mesh(0));
    assets::Node root;
    root.meshes = {0};
    model.nodes.push_back(std::move(root));
    model.root_node = 0;

    scenegraph::World world;
    auto h = reinterpret_cast<scenegraph::ModelHandle>(&model);
    auto iid_space = world.create_instance(h);   // default Pass::Space
    auto iid_bridge = world.create_instance(h);
    world.set_pass(iid_bridge, scenegraph::Pass::Bridge);
    (void)iid_space;

    int count = 0;
    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 1);  // only the bridge-tagged instance
}
