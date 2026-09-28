#include <gtest/gtest.h>
#include "model_build.h"
#include "link_resolver.h"

#include <assets/cache.h>
#include <assets/mesh_fix.h>
#include <nif/block.h>
#include <nif/file.h>

#include "support/content_root.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

inline int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return ::getpid();
#endif
}

assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(
        /*vao=*/0, /*vbo=*/0, /*ebo=*/0,
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

assets::AssetCache::Config stub_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = stub_texture;
    cfg.mesh_uploader = stub_mesh;
    return cfg;
}

// 2x1 RGBA PNG, same bytes as texture_decode_test.cc's make_png_rgba_2x1().
// Pixel 0: opaque red. Pixel 1: half-transparent blue.
std::vector<std::uint8_t> png_2x1_rgba() {
    return {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0xf4, 0x22, 0x7f, 0x8a, 0x00, 0x00, 0x00,
        0x0e, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
        0x42, 0x0d, 0x00, 0x0f, 0x7a, 0x03, 0x7e, 0x77, 0xe9, 0x7f, 0x97, 0x00,
        0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    };
}

std::string file_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

class DecalBuildTest : public ::testing::Test {
protected:
    fs::path tmp_dir;
    assets::PathResolver resolver;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "assets-decal";
        for (int i = 0; ; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(current_pid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
    }
    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }

    fs::path write_png(const std::string& name) {
        auto bytes = png_2x1_rgba();
        auto path = tmp_dir / name;
        std::ofstream out(path, std::ios::binary);
        out.write(reinterpret_cast<const char*>(bytes.data()),
                  static_cast<std::streamsize>(bytes.size()));
        return path;
    }

    // Root NiNode -> two NiTriShapes named "a" and "b", each with a minimal
    // triangle. Identity link ids (no block_ids), matching model_build_test's
    // synthetic-file convention.
    nif::File file_with_two_named_shapes() {
        nif::File f;
        nif::NiNode root;               // block 0
        root.av.obj.name = "Root";
        root.child_links = {1, 3};
        f.blocks.push_back(root);

        auto add_shape = [&](const char* name, std::uint32_t data_block) {
            nif::NiTriShape tri;
            tri.av.obj.name = name;
            tri.data_link = data_block;
            f.blocks.push_back(tri);
            nif::NiTriShapeData d;
            d.num_vertices = 3;
            d.has_vertices = true;
            d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
            d.has_uv = true;
            d.uv_sets.push_back({{0, 0}, {1, 0}, {0, 1}});
            d.num_triangles = 1;
            d.triangles.push_back({0, 1, 2});
            f.blocks.push_back(d);
        };
        // blocks 1..2 (shape "a"), 3..4 (shape "b"), identity link ids.
        add_shape("a", 2);
        add_shape("b", 4);
        return f;
    }

    assets::detail::ModelBuildContext make_ctx() {
        assets::detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_paths = {tmp_dir};
        ctx.texture_uploader = stub_texture;
        ctx.mesh_uploader = stub_mesh;
        return ctx;
    }

    static const assets::Material::TextureStage& decal_stage(
        const assets::Model& m, std::size_t material_index) {
        return m.materials[material_index]
            .stages[static_cast<std::size_t>(
                assets::Material::StageSlot::Decal0)];
    }
};

}  // namespace

// --- decal_body_to_mask -----------------------------------------------

TEST(DecalProjector, MapsCornersToUnitSquare) {
    const glm::vec3 origin{10.0f, 20.0f, 30.0f};
    const glm::vec3 u{5.0f, 0.0f, 0.0f};
    const glm::vec3 v{0.0f, 2.0f, 0.0f};
    const glm::vec3 n{0.0f, 0.0f, 1.0f};

    auto m = assets::detail::decal_body_to_mask(origin, u, v, n);

    auto to = [&](const glm::vec3& p) {
        return glm::vec3(m * glm::vec4(p, 1.0f));
    };

    const glm::vec3 at_origin = to(origin);
    const glm::vec3 at_u = to(origin + u);
    const glm::vec3 at_v = to(origin + v);
    const glm::vec3 at_n = to(origin + 3.0f * n);

    EXPECT_NEAR(at_origin.x, 0.0f, 1e-5f);
    EXPECT_NEAR(at_origin.y, 0.0f, 1e-5f);
    EXPECT_NEAR(at_origin.z, 0.0f, 1e-5f);

    EXPECT_NEAR(at_u.x, 1.0f, 1e-5f);
    EXPECT_NEAR(at_u.y, 0.0f, 1e-5f);
    EXPECT_NEAR(at_u.z, 0.0f, 1e-5f);

    EXPECT_NEAR(at_v.x, 0.0f, 1e-5f);
    EXPECT_NEAR(at_v.y, 1.0f, 1e-5f);
    EXPECT_NEAR(at_v.z, 0.0f, 1e-5f);

    EXPECT_NEAR(at_n.x, 0.0f, 1e-5f);
    EXPECT_NEAR(at_n.y, 0.0f, 1e-5f);
    EXPECT_NEAR(at_n.z, 3.0f, 1e-5f);
}

// A mirrored basis (u x v pointing AGAINST the stated normal) is still
// invertible -- only a near-zero determinant is degenerate (see
// model_build.cc's apply_decals). The generator can hand us either handedness;
// decal_body_to_mask itself must not care.
TEST(DecalProjector, MapsCornersToUnitSquareMirroredBasis) {
    const glm::vec3 origin{0.0f, 0.0f, 0.0f};
    const glm::vec3 u{1.0f, 0.0f, 0.0f};
    const glm::vec3 v{0.0f, 1.0f, 0.0f};
    // Normal chosen so that dot(cross(u, v), normal) < 0 -- mirrored.
    const glm::vec3 n{0.0f, 0.0f, -1.0f};

    auto m = assets::detail::decal_body_to_mask(origin, u, v, n);
    auto to = [&](const glm::vec3& p) {
        return glm::vec3(m * glm::vec4(p, 1.0f));
    };

    EXPECT_NEAR(to(origin + u).x, 1.0f, 1e-5f);
    EXPECT_NEAR(to(origin + u).y, 0.0f, 1e-5f);
    EXPECT_NEAR(to(origin + v).x, 0.0f, 1e-5f);
    EXPECT_NEAR(to(origin + v).y, 1.0f, 1e-5f);
    // Along the (negated) normal, w should read +2 at origin + 2*n.
    EXPECT_NEAR(to(origin + 2.0f * n).z, 2.0f, 1e-5f);
}

// --- build_model: attaching a decal to a named shape's material --------

TEST_F(DecalBuildTest, AttachesToNamedShapeOnly) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "a";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {0.0f, 1.0f, 0.0f};
    req.normal = {0.0f, 0.0f, 1.0f};
    req.depth = 2.0f;
    req.mask = mask;
    ctx.decals = {req};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.materials.size(), 2u);

    // Shape "a" was declared first, so it's materials[0]; "b" is materials[1].
    EXPECT_GE(decal_stage(model, 0).texture_index, 0);
    EXPECT_TRUE(model.materials[0].decal.enabled);

    EXPECT_EQ(decal_stage(model, 1).texture_index, -1);
    EXPECT_FALSE(model.materials[1].decal.enabled);
}

TEST_F(DecalBuildTest, UnknownShapeIsSkippedWithoutThrowing) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "does-not-exist";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {0.0f, 1.0f, 0.0f};
    req.normal = {0.0f, 0.0f, 1.0f};
    req.mask = mask;
    ctx.decals = {req};

    assets::Model model;
    ASSERT_NO_THROW(model = assets::detail::build_model(f, ctx));
    for (const auto& mat : model.materials) EXPECT_FALSE(mat.decal.enabled);
}

TEST_F(DecalBuildTest, MissingMaskFileIsSkippedWithoutThrowing) {
    auto f = file_with_two_named_shapes();

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "a";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {0.0f, 1.0f, 0.0f};
    req.normal = {0.0f, 0.0f, 1.0f};
    req.mask = tmp_dir / "does-not-exist.png";
    ctx.decals = {req};

    assets::Model model;
    ASSERT_NO_THROW(model = assets::detail::build_model(f, ctx));
    for (const auto& mat : model.materials) EXPECT_FALSE(mat.decal.enabled);
}

TEST_F(DecalBuildTest, DegenerateProjectorIsSkippedWithoutThrowing) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "a";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {2.0f, 0.0f, 0.0f};  // parallel to u_axis -> |u x v| == 0
    req.normal = {0.0f, 0.0f, 1.0f};
    req.mask = mask;
    ctx.decals = {req};

    assets::Model model;
    ASSERT_NO_THROW(model = assets::detail::build_model(f, ctx));
    for (const auto& mat : model.materials) EXPECT_FALSE(mat.decal.enabled);
}

// --- AssetCache: distinct registries -> distinct cache entries ---------

namespace {

fs::path ambassador_nif_path() {
    return test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
}
fs::path ambassador_high_path() {
    return test_support::game_root() / "data/Models/Ships/Ambassador/High";
}
bool game_data_present() {
    return fs::exists(ambassador_nif_path());
}
fs::path zhukov_top_mask() {
    return test_support::project_root() /
        "native/assets/replacements/data/Models/Ships/Ambassador/Masks/Zhukov/top.png";
}
fs::path excalibur_top_mask() {
    return test_support::project_root() /
        "native/assets/replacements/data/Models/Ships/Ambassador/Masks/Excalibur/top.png";
}

assets::DecalRequest top_decal_request(const fs::path& mask) {
    assets::DecalRequest req;
    req.shape = "amb saucer:0";
    req.origin = {58.13181686401367f, 149.3275146484375f, 51.149471282958984f};
    req.u_axis = {-119.56663513183594f, -0.011889359913766384f, -0.0024647493846714497f};
    req.v_axis = {-0.005896189250051975f, 59.74415969848633f, -2.1634225845336914f};
    req.normal = {-2.4198923711082898e-05f, 0.03618772700428963f, 0.9993450045585632f};
    req.depth = 2.0f;
    req.mask = mask;
    return req;
}

}  // namespace

TEST(DecalCache, RegistriesAreSeparateEntries) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();
    ASSERT_TRUE(fs::exists(excalibur_top_mask())) << excalibur_top_mask();

    assets::AssetCache cache(stub_config());
    std::vector<fs::path> search{ambassador_high_path()};

    auto zhukov_a = cache.load(ambassador_nif_path(), search, {},
                                {top_decal_request(zhukov_top_mask())});
    auto zhukov_b = cache.load(ambassador_nif_path(), search, {},
                                {top_decal_request(zhukov_top_mask())});
    EXPECT_EQ(zhukov_a.get(), zhukov_b.get());

    auto excalibur = cache.load(ambassador_nif_path(), search, {},
                                 {top_decal_request(excalibur_top_mask())});
    EXPECT_NE(zhukov_a.get(), excalibur.get());
}

// --- Frame agreement: decals.json's frame IS the renderer's model frame ---

namespace {

// Block-array index of the NiTriShape whose av.obj.name == `name`, or
// nif::File::blocks.size() if not found.
std::size_t find_shape_block(const nif::File& f, const std::string& name) {
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        if (const auto* s = std::get_if<nif::NiTriShape>(&f.blocks[i])) {
            if (s->av.obj.name == name) return i;
        }
    }
    return f.blocks.size();
}

// Block-array index of the NiNode whose (resolved) child_links contains
// `child_block_idx`, or f.blocks.size() if none does. Mirrors
// model_build.cc's find_parent_node_index / mesh_fix.cc's parent_of.
std::size_t find_parent_node_block(
    const nif::File& f, std::size_t child_block_idx,
    const assets::detail::LinkResolver& resolver) {
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto link : node->child_links) {
            if (resolver.resolve(link) == child_block_idx) return i;
        }
    }
    return f.blocks.size();
}

}  // namespace

TEST(DecalFrame, NifBlockWorldMatchesModelNodeChain) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    nif::File f = nif::load(ambassador_nif_path());
    const std::string kShapeName = "amb saucer:0";

    const std::size_t shape_block = find_shape_block(f, kShapeName);
    ASSERT_LT(shape_block, f.blocks.size()) << "shape not found in Ambassador.nif";

    assets::detail::LinkResolver resolver(f);
    const std::size_t node_block =
        find_parent_node_block(f, shape_block, resolver);
    ASSERT_LT(node_block, f.blocks.size()) << "shape has no parent NiNode";
    const std::string node_name =
        std::get<nif::NiNode>(f.blocks[node_block]).av.obj.name;

    // Build the model the normal way (no decals) and find the Node whose
    // name matches the shape's parent NiNode -- the frame decals.json is
    // authored in reaches the renderer only through this Node's local
    // transform chain (Model::nodes), never the shape's own block index.
    assets::PathResolver path_resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &path_resolver;
    ctx.texture_search_paths = {ambassador_high_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    auto model = assets::detail::build_model(f, ctx);

    int model_node_index = -1;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name == node_name) {
            model_node_index = static_cast<int>(i);
            break;
        }
    }
    ASSERT_GE(model_node_index, 0) << "no Model::nodes entry named " << node_name;

    // Compose model.nodes local transforms root -> model_node_index, exactly
    // as frame.cc's world_per_node walk does (minus the instance `world`
    // factor, which is the whole point -- ship-body frame has it removed).
    glm::mat4 composed(1.0f);
    {
        std::vector<int> chain;
        for (int i = model_node_index; i >= 0; i = model.nodes[i].parent_index)
            chain.push_back(i);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            composed = composed * model.nodes[*it].local_transform;
    }

    const glm::mat4 expected = assets::nif_block_world(f, shape_block);

    float max_diff = 0.0f;
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 4; ++r)
            max_diff = std::max(max_diff, std::abs(composed[c][r] - expected[c][r]));

    // Recorded for the task report regardless of pass/fail.
    std::fprintf(stderr, "[DecalFrame] max component difference = %g\n",
                 static_cast<double>(max_diff));

    EXPECT_LT(max_diff, 1e-4f)
        << "composed (node chain only):\n"
        << composed[0][0] << " " << composed[1][0] << " " << composed[2][0] << " " << composed[3][0] << "\n"
        << composed[0][1] << " " << composed[1][1] << " " << composed[2][1] << " " << composed[3][1] << "\n"
        << composed[0][2] << " " << composed[1][2] << " " << composed[2][2] << " " << composed[3][2] << "\n"
        << composed[0][3] << " " << composed[1][3] << " " << composed[2][3] << " " << composed[3][3] << "\n"
        << "expected (nif_block_world of shape block):\n"
        << expected[0][0] << " " << expected[1][0] << " " << expected[2][0] << " " << expected[3][0] << "\n"
        << expected[0][1] << " " << expected[1][1] << " " << expected[2][1] << " " << expected[3][1] << "\n"
        << expected[0][2] << " " << expected[1][2] << " " << expected[2][2] << " " << expected[3][2] << "\n"
        << expected[0][3] << " " << expected[1][3] << " " << expected[2][3] << " " << expected[3][3] << "\n";
}
