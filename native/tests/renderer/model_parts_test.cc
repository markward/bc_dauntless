// Part candidates are the children of 'Scene Root'. Measured on the real
// BirdOfPrey.nif with native/tools/dump_nif_tree:
//
//   [5] NiNode 'Scene Root'  (children=4)
//         [6]  'head'        [20] 'left wing'
//         [32] 'left wing01' [42] 'birdofprey'
//
// 'Scene Root' itself sits under two UNNAMED wrapper nodes, and every part's
// geometry hangs off an interposed '__NDL_MultiMtl_Node' -- a 3ds Max exporter
// artifact. A real hull is THREE levels, and a two-level fixture is what let a
// picking bug reach live play in the preceding work.

#include <gtest/gtest.h>

#include <cstdlib>
#include <filesystem>
#include <set>
#include <string>
#include <vector>

#include <glm/gtc/matrix_transform.hpp>

#include <assets/model.h>
#include <renderer/model_parts.h>

#include "model_build.h"
#include "support/content_root.h"

namespace {

int add_node(assets::Model& m, const char* name, int parent,
             const glm::mat4& xf = glm::mat4(1.0f)) {
    const int idx = static_cast<int>(m.nodes.size());
    m.nodes.push_back(assets::Node{
        .name = name, .parent_index = parent, .local_transform = xf,
    });
    if (parent >= 0) m.nodes[parent].children.push_back(idx);
    return idx;
}

int add_unit_cube_mesh(assets::Model& m) {
    assets::MeshCpu cpu;
    cpu.vertices.push_back({.position = glm::vec3(-1, -1, -1)});
    cpu.vertices.push_back({.position = glm::vec3(1, -1, 1)});
    cpu.vertices.push_back({.position = glm::vec3(1, 1, 1)});
    cpu.indices = {0u, 1u, 2u};
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));
    return static_cast<int>(m.meshes.size()) - 1;
}

// Two unnamed wrappers -> 'Scene Root' -> two parts -> __NDL -> mesh.
assets::Model bop_shaped_model() {
    assets::Model m;
    m.root_node = 0;
    const int w0 = add_node(m, "", -1);
    const int w1 = add_node(m, "", w0);
    const int root = add_node(m, "Scene Root", w1);
    const int mesh = add_unit_cube_mesh(m);

    const int wing = add_node(m, "left wing", root,
                              glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)));
    const int wing_mtl = add_node(m, "__NDL_MultiMtl_Node", wing);
    m.nodes[wing_mtl].meshes.push_back(mesh);

    const int body = add_node(m, "birdofprey", root);
    const int body_mtl = add_node(m, "__NDL_MultiMtl_Node", body);
    m.nodes[body_mtl].meshes.push_back(mesh);
    return m;
}

const renderer::ModelPart* find(const std::vector<renderer::ModelPart>& v,
                                const std::string& name) {
    for (const auto& p : v) if (p.name == name) return &p;
    return nullptr;
}

}  // namespace

TEST(ModelParts, SceneRootsChildrenAreTheCandidates) {
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* wing = find(parts, "left wing");
    const auto* body = find(parts, "birdofprey");
    ASSERT_NE(wing, nullptr);
    ASSERT_NE(body, nullptr);
    EXPECT_TRUE(wing->candidate);
    EXPECT_TRUE(body->candidate);
}

TEST(ModelParts, PlumbingAndWrappersAreNotCandidates) {
    // The thing that makes the list usable. __NDL_MultiMtl_Node is exporter
    // plumbing and 'Scene Root' is not itself a part.
    const auto parts = renderer::model_parts(bop_shaped_model());
    for (const auto& p : parts) {
        if (p.name == "__NDL_MultiMtl_Node" || p.name == "Scene Root" || p.name.empty()) {
            EXPECT_FALSE(p.candidate) << p.name << " must not be a candidate";
        }
    }
}

TEST(ModelParts, BoundsIncludeDESCENDANTGeometry) {
    // THE TRAP. A part node carries no meshes of its own -- they hang off its
    // __NDL child. Bounds built from a node's OWN meshes would be empty for
    // every part on every real hull.
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* wing = find(parts, "left wing");
    ASSERT_NE(wing, nullptr);
    ASSERT_TRUE(wing->has_bounds) << "a part's bounds come from its descendants";
    EXPECT_NEAR(wing->bounds_min.x, 9.0f, 1e-4f);
    EXPECT_NEAR(wing->bounds_max.x, 11.0f, 1e-4f);
}

TEST(ModelParts, BoundsAreRestPoseAndIncludeTheNodeChain) {
    // The wing is translated +10 by its own local_transform; the body is not.
    const auto parts = renderer::model_parts(bop_shaped_model());
    const auto* body = find(parts, "birdofprey");
    ASSERT_NE(body, nullptr);
    ASSERT_TRUE(body->has_bounds);
    EXPECT_NEAR(body->bounds_min.x, -1.0f, 1e-4f);
    EXPECT_NEAR(body->bounds_max.x, 1.0f, 1e-4f);
}

TEST(ModelParts, ANodeWithNoGeometryAnywhereHasNoBounds) {
    assets::Model m;
    m.root_node = 0;
    const int root = add_node(m, "Scene Root", -1);
    add_node(m, "empty", root);
    const auto parts = renderer::model_parts(m);
    const auto* empty = find(parts, "empty");
    ASSERT_NE(empty, nullptr);
    EXPECT_FALSE(empty->has_bounds);
}

TEST(ModelParts, FallsBackToTheFirstBranchingNodeWithoutASceneRoot) {
    // Not every hull names its root 'Scene Root'. The rule degrades to "the
    // first node with more than one child" rather than returning nothing --
    // and NOT to model.root_node itself. w0 IS model.root_node but has only
    // ONE child (w1); the first BRANCHING node is w1, two levels below root,
    // mirroring BirdOfPrey.nif's two unnamed wrappers above Scene Root. A
    // fallback that wrongly returned model.root_node would make w0 the part
    // parent, and since no node's parent is w0, every part would come back
    // candidate=false -- this fixture is the one that would catch that.
    assets::Model m;
    m.root_node = 0;
    const int w0 = add_node(m, "", -1);
    const int w1 = add_node(m, "", w0);
    const int mesh = add_unit_cube_mesh(m);
    const int a = add_node(m, "alpha", w1);
    const int b = add_node(m, "beta", w1);
    m.nodes[a].meshes.push_back(mesh);
    m.nodes[b].meshes.push_back(mesh);

    const auto parts = renderer::model_parts(m);
    const auto* alpha = find(parts, "alpha");
    const auto* beta = find(parts, "beta");
    ASSERT_NE(alpha, nullptr);
    ASSERT_NE(beta, nullptr);
    EXPECT_TRUE(alpha->candidate);
    EXPECT_TRUE(beta->candidate);
}

// ── Content-gated: the REAL BirdOfPrey.nif ──────────────────────────────────
//
// Every test above runs against a SYNTHETIC three-level fixture built to
// mirror what this file's header comment says was measured on the real hull
// with native/tools/dump_nif_tree. Nothing before this point ever actually
// loads BirdOfPrey.nif and asks model_parts() the same question -- so a
// real-world mismatch (wrong case, a stray whitespace, "Scene Root" not
// being the part parent on this particular hull) would ship invisibly behind
// an all-green suite. articulation.py's whole Bird-of-Prey rig (severance,
// wing-follow) is keyed on these exact four names, so if this ever fails,
// STOP and report it -- it is a real discovery about the asset, not
// something to quietly work around.
namespace {

// Stubs return zero IDs so destructors short-circuit (no GL context here) --
// mirrors native/tests/assets/cpu/model_build_test.cc's stub_texture/stub_mesh.
assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(
        /*vao=*/0, /*vbo=*/0, /*ebo=*/0,
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

}  // namespace

TEST(ModelParts, RealBirdOfPreyExposesExactlyTheFourCandidates) {
    namespace fs = std::filesystem;
    const fs::path game_dir = test_support::game_root();
    const fs::path nif = game_dir / "data/Models/Ships/BirdOfPrey/BirdOfPrey.nif";
    if (!fs::is_regular_file(nif)) {
        GTEST_SKIP() << "no BC install / BirdOfPrey.nif under \"" << game_dir
                     << "\" -- set DAUNTLESS_GAME_DIR to run this test";
    }

    nif::File f = nif::load(nif);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    // model_parts() sweeps mesh.cpu_data() to compute per-part bounds
    // (aabb.cc-style); without this the meshes upload and discard their CPU
    // vertices, and every part comes back has_bounds=false.
    ctx.keep_cpu_data = true;
    auto model = assets::detail::build_model(f, ctx);

    const auto parts = renderer::model_parts(model);
    ASSERT_FALSE(parts.empty()) << "BirdOfPrey.nif produced no named nodes at all";

    std::set<std::string> candidates;
    for (const auto& p : parts) {
        if (p.candidate) candidates.insert(p.name);
    }
    EXPECT_EQ(candidates, (std::set<std::string>{
                  "head", "left wing", "left wing01", "birdofprey"}))
        << "the real hull's candidate set no longer matches what "
           "engine/appc/hardpoint_overrides.py's BoP rig and "
           "articulation.part_boxes_for assume -- this is a genuine "
           "discovery, not something to work around here";

    for (const auto& p : parts) {
        if (p.name == "__NDL_MultiMtl_Node") {
            EXPECT_FALSE(p.candidate)
                << "the exporter-marker node must never be a candidate";
        }
    }

    for (const auto& name : candidates) {
        const auto* part = find(parts, name);
        ASSERT_NE(part, nullptr);
        EXPECT_TRUE(part->has_bounds) << name << " must have bounds";
    }
}
