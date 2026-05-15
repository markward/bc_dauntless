// native/tests/renderer/bridge_pass_test.cc
//
// CPU-side test that BridgePass partitions bridge-tagged meshes by
// Material::lightmap_pass. We cannot invoke BridgePass::render() here
// (it issues real GL calls), so we verify partitioning by counting
// matching meshes in a fake Model+World; the BridgePass implementation
// uses the same predicate (mat.lightmap_pass == want_lightmap_pass).
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

TEST(BridgePassPartitioning, CountsBaseAndLightmapMeshesSeparately) {
    assets::Model model;
    model.materials.push_back(assets::Material{});                 // 0 base
    model.materials.push_back(assets::Material{});                 // 1 base
    {
        assets::Material lm;
        lm.lightmap_pass = true;
        model.materials.push_back(std::move(lm));                  // 2 lm
    }
    model.meshes.push_back(make_stub_mesh(0));
    model.meshes.push_back(make_stub_mesh(1));
    model.meshes.push_back(make_stub_mesh(2));
    assets::Node root;
    root.meshes = {0, 1, 2};
    model.nodes.push_back(std::move(root));
    model.root_node = 0;

    scenegraph::World world;
    auto h = reinterpret_cast<scenegraph::ModelHandle>(&model);
    auto iid = world.create_instance(h);
    world.set_pass(iid, scenegraph::Pass::Bridge);

    int base_count = 0, lm_count = 0;
    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            const auto* m = reinterpret_cast<const assets::Model*>(inst.model_handle);
            for (const auto& mesh : m->meshes) {
                const auto& mat = m->materials[mesh.material_index()];
                if (mat.lightmap_pass) ++lm_count;
                else                    ++base_count;
            }
        });

    EXPECT_EQ(base_count, 2);
    EXPECT_EQ(lm_count, 1);
}

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
