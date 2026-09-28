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

    // 2x1 24-bit uncompressed TGA -- same bytes as texture_decode_test.cc's
    // make_tga_24bit_2x1() -- decodes to RGB8 with NO alpha channel, so it
    // exercises apply_decals' no-alpha warning path.
    fs::path write_tga_no_alpha(const std::string& name) {
        const std::vector<std::uint8_t> bytes = {
            0, 0, 2,
            0, 0, 0, 0, 0,
            0, 0, 0, 0,
            2, 0, 1, 0,
            24,
            0,
            0x00, 0x00, 0xFF,
            0xFF, 0x00, 0x00,
        };
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
    // clamp_mode holds the NIF TexClampMode encoding (0 == CLAMP_S_CLAMP_T),
    // NOT a GL enum -- GL_CLAMP_TO_EDGE (0x812F) would fail this. Task 5
    // applies the actual GL wrap mode at bind time.
    EXPECT_EQ(decal_stage(model, 0).clamp_mode, 0u);

    EXPECT_EQ(decal_stage(model, 1).texture_index, -1);
    EXPECT_FALSE(model.materials[1].decal.enabled);
}

TEST_F(DecalBuildTest, ZeroNormalIsSkippedWithoutThrowing) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "a";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {0.0f, 1.0f, 0.0f};
    req.normal = {0.0f, 0.0f, 0.0f};  // zero -> normalize() would be NaN
    req.mask = mask;
    ctx.decals = {req};

    assets::Model model;
    ASSERT_NO_THROW(model = assets::detail::build_model(f, ctx));
    for (const auto& mat : model.materials) EXPECT_FALSE(mat.decal.enabled);
}

TEST_F(DecalBuildTest, InPlaneNormalIsSkippedWithoutThrowing) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    assets::DecalRequest req;
    req.shape = "a";
    req.origin = {0.0f, 0.0f, 0.0f};
    req.u_axis = {1.0f, 0.0f, 0.0f};
    req.v_axis = {0.0f, 1.0f, 0.0f};
    // Lies in span(u_axis, v_axis) -> det([u v n]) == 0 -> inverse() would
    // be inf/NaN even though u_axis x v_axis is perfectly healthy.
    req.normal = {1.0f, 1.0f, 0.0f};
    req.mask = mask;
    ctx.decals = {req};

    assets::Model model;
    ASSERT_NO_THROW(model = assets::detail::build_model(f, ctx));
    for (const auto& mat : model.materials) EXPECT_FALSE(mat.decal.enabled);
}

// Ruling: one decal per shape material, first request wins. A second
// request targeting an already-decaled material is skipped (with a
// warning), not silently overwriting the first.
TEST_F(DecalBuildTest, SecondDecalOnSameShapeIsSkippedFirstWins) {
    auto f = file_with_two_named_shapes();
    auto mask1 = write_png("mask1.png");
    auto mask2 = write_png("mask2.png");

    auto ctx = make_ctx();
    assets::DecalRequest req1;
    req1.shape = "a";
    req1.origin = {0.0f, 0.0f, 0.0f};
    req1.u_axis = {1.0f, 0.0f, 0.0f};
    req1.v_axis = {0.0f, 1.0f, 0.0f};
    req1.normal = {0.0f, 0.0f, 1.0f};
    req1.mask = mask1;

    assets::DecalRequest req2 = req1;
    req2.mask = mask2;

    ctx.decals = {req1, req2};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.materials.size(), 2u);
    EXPECT_TRUE(model.materials[0].decal.enabled);
    EXPECT_GE(decal_stage(model, 0).texture_index, 0);
    // Only the first decal's texture was ever uploaded -- a second upload
    // (from the wrongly-applied second request) would make this 2.
    EXPECT_EQ(model.textures.size(), 1u);
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

// --- Mesh-fix gate (Controller Ruling G item 1) -----------------------
//
// A decal is only ever attached on top of a SUCCESSFULLY PATCHED mesh: the
// merged saucer no longer carries BC's own "ID" patch geometry, so painting
// a decal on top of it is the only name drawn. On an unpatched load (no
// mesh_fix_dir configured, no fix file matched, or a fix that parsed but
// was refused) BC's own ID-patch shape is still there and would paint its
// own name -- attaching our decal too would draw the name twice.

namespace {
std::string decal_file_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss; ss << in.rdbuf(); return ss.str();
}
fs::path committed_mesh_fixes_dir() {
    return fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/mesh_fixes";
}
fs::path decal_temp_fix_dir(const char* tag) {
    auto d = fs::temp_directory_path() / (std::string("dauntless_decal_gate_") + tag);
    fs::remove_all(d); fs::create_directories(d); return d;
}
}  // namespace

// All three DecalCache/DecalMeshFixGate tests below now configure
// mesh_fix_dir to the committed fixes tree so decals actually attach.
TEST(DecalCache, RegistriesAreSeparateEntries) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();
    ASSERT_TRUE(fs::exists(excalibur_top_mask())) << excalibur_top_mask();

    auto cfg = stub_config();
    cfg.mesh_fix_dir = [] { return committed_mesh_fixes_dir(); };
    assets::AssetCache cache(cfg);
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

// (a) real Ambassador + the committed fixes dir + a decal -> attached.
TEST(DecalMeshFixGate, AttachedWhenMeshFixApplies) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    auto cfg = stub_config();
    cfg.mesh_fix_dir = [] { return committed_mesh_fixes_dir(); };
    assets::AssetCache cache(cfg);
    auto model = cache.load(ambassador_nif_path(), {ambassador_high_path()}, {},
                             {top_decal_request(zhukov_top_mask())});

    int decaled = 0;
    for (const auto& m : model->materials) decaled += m.decal.enabled ? 1 : 0;
    EXPECT_GT(decaled, 0) << "decal should attach when the mesh fix applies";
}

// (b) real Ambassador with NO mesh_fix_dir + a decal -> not attached, one
// warning naming the nif and the reason.
TEST(DecalMeshFixGate, NotAttachedWithoutMeshFixDirConfigured) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    assets::AssetCache cache(stub_config());  // no mesh_fix_dir at all
    testing::internal::CaptureStderr();
    auto model = cache.load(ambassador_nif_path(), {ambassador_high_path()}, {},
                             {top_decal_request(zhukov_top_mask())});
    const std::string err = testing::internal::GetCapturedStderr();

    for (const auto& m : model->materials) EXPECT_FALSE(m.decal.enabled);
    EXPECT_NE(err.find("hull decals skipped for"), std::string::npos) << err;
    EXPECT_NE(err.find("no mesh fix applied"), std::string::npos) << err;
}

// (c) a fix that is refused -> not attached.
TEST(DecalMeshFixGate, NotAttachedWhenMeshFixIsRefused) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    auto dir = decal_temp_fix_dir("refused");
    std::ofstream(dir / (assets::fnv1a64_hex(decal_file_bytes(ambassador_nif_path())) + ".json"))
        << R"({"format":1,"merges":[{"patch":{"block":0,"name":"nope"},
              "target":{"block":1,"name":"nope"},"uvs":[],"weld":[],"normals":null}]})";

    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache cache(cfg);
    auto model = cache.load(ambassador_nif_path(), {ambassador_high_path()}, {},
                             {top_decal_request(zhukov_top_mask())});

    for (const auto& m : model->materials) EXPECT_FALSE(m.decal.enabled);
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

}  // namespace

// Proves decals.json's authored frame (nif_block_world on the shape's own
// NIF block, applied to a RAW NiTriShapeData vertex) agrees with the
// renderer's actual draw-time frame for that same vertex: mesh_build.cc
// bakes the NiTriShape's own `av` transform into the CPU vertex
// (mesh_build.cc:56-65), and frame.cc then multiplies by the composed
// Model::nodes chain UP TO the mesh's node (frame.cc:680-689) -- never the
// shape's own block. A test that only composed the node chain (no real
// vertex) would pass vacuously whenever the shape's own `av` happens to be
// identity; going through real vertices catches a baked-transform bug that
// vacuous test cannot.
TEST(DecalFrame, NifBlockWorldMatchesModelNodeChain) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(zhukov_top_mask())) GTEST_SKIP() << "Zhukov/top.png not installed";

    nif::File f = nif::load(ambassador_nif_path());
    const std::string kShapeName = "amb saucer:0";

    const std::size_t shape_block = find_shape_block(f, kShapeName);
    ASSERT_LT(shape_block, f.blocks.size()) << "shape not found in Ambassador.nif";

    // Raw (untransformed) NiTriShapeData vertices for that same shape --
    // build_mesh_cpu writes mesh.vertices[i] from data.vertices[i] with no
    // reindexing, so index i means the same vertex on both sides.
    const auto& shape_var = std::get<nif::NiTriShape>(f.blocks[shape_block]);
    assets::detail::LinkResolver link_resolver(f);
    const auto data_idx = link_resolver.resolve(shape_var.data_link);
    ASSERT_NE(data_idx, assets::detail::LinkResolver::kInvalidIndex);
    ASSERT_LT(data_idx, f.blocks.size());
    const auto* data = std::get_if<nif::NiTriShapeData>(&f.blocks[data_idx]);
    ASSERT_NE(data, nullptr);
    ASSERT_TRUE(data->has_vertices);
    ASSERT_FALSE(data->vertices.empty());

    // Build WITH keep_cpu_data (to read the vertices back) and a decal
    // targeting this shape (so the right Mesh can be found unambiguously
    // via Material::decal.enabled, rather than re-deriving build_model's
    // shape-selection/skip logic here).
    assets::PathResolver path_resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &path_resolver;
    ctx.texture_search_paths = {ambassador_high_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;
    ctx.decals = {top_decal_request(zhukov_top_mask())};
    auto model = assets::detail::build_model(f, ctx);

    int decal_material = -1;
    for (std::size_t i = 0; i < model.materials.size(); ++i) {
        if (model.materials[i].decal.enabled) {
            decal_material = static_cast<int>(i);
            break;
        }
    }
    ASSERT_GE(decal_material, 0) << "decal was not attached to any material";

    const assets::Mesh* mesh = nullptr;
    for (const auto& m : model.meshes) {
        if (m.material_index() == decal_material) { mesh = &m; break; }
    }
    ASSERT_NE(mesh, nullptr);
    ASSERT_TRUE(mesh->cpu_data().has_value());
    const auto& cpu = *mesh->cpu_data();
    ASSERT_EQ(cpu.vertices.size(), data->vertices.size());

    // Compose model.nodes local transforms root -> mesh's node, exactly as
    // frame.cc:680-689's world_per_node walk does (minus the instance
    // `world` factor -- ship-body frame has it removed by construction).
    glm::mat4 chain(1.0f);
    {
        std::vector<int> path;
        for (int i = mesh->node_index(); i >= 0; i = model.nodes[i].parent_index)
            path.push_back(i);
        for (auto it = path.rbegin(); it != path.rend(); ++it)
            chain = chain * model.nodes[*it].local_transform;
    }

    const glm::mat4 expected_chain = assets::nif_block_world(f, shape_block);

    // Sample several vertices spread across the shape.
    float max_diff = 0.0f;
    std::size_t sampled = 0;
    const std::size_t n = cpu.vertices.size();
    const std::size_t stride = std::max<std::size_t>(1, n / 8);
    for (std::size_t i = 0; i < n; i += stride) {
        const glm::vec3 actual =
            glm::vec3(chain * glm::vec4(cpu.vertices[i].position, 1.0f));
        const auto& raw = data->vertices[i];
        const glm::vec3 expected = glm::vec3(
            expected_chain * glm::vec4(raw.x, raw.y, raw.z, 1.0f));
        max_diff = std::max(max_diff, glm::length(actual - expected));
        ++sampled;
    }

    // Recorded for the task report regardless of pass/fail.
    std::fprintf(stderr,
        "[DecalFrame] max vertex difference = %g (sampled %zu of %zu vertices)\n",
        static_cast<double>(max_diff), sampled, n);

    EXPECT_LT(max_diff, 1e-3f);
}

// --- Premultiplied mask (spec §2 implementation note) ------------------

// apply_decals premultiplies the decoded mask's RGB by alpha BEFORE upload,
// so bilinear/mip filtering never drags the black RGB of transparent texels
// into letter edges as a dark halo. opaque.frag composites
// base.rgb * (1 - a) + mask.rgb (already premultiplied).
TEST_F(DecalBuildTest, MaskIsPremultipliedBeforeUpload) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    std::vector<assets::Image> uploaded;
    auto ctx = make_ctx();
    ctx.texture_uploader = [&uploaded](const assets::Image& img, bool mips) {
        uploaded.push_back(img);
        return stub_texture(img, mips);
    };
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
    ASSERT_TRUE(model.materials[0].decal.enabled);
    ASSERT_EQ(uploaded.size(), 1u);  // the synthetic shapes have no textures
    const auto& img = uploaded.back();
    ASSERT_EQ(img.format, assets::Image::Format::RGBA8);
    // Pixel 0 opaque red is unchanged; pixel 1 (00 00 FF 80) becomes
    // blue * 128/255 = 128, alpha kept.
    const std::vector<std::uint8_t> expected = {0xFF, 0x00, 0x00, 0xFF,
                                                0x00, 0x00, 0x80, 0x80};
    EXPECT_EQ(img.pixels, expected);
}

// --- No-alpha mask (Controller Ruling G item 4) -------------------------

// An RGB8/R8 mask has no alpha channel to sample -- apply_decals treats it
// as fully opaque (the whole rectangle painted) but must warn once, since a
// silently-opaque decal that was meant to be a soft-edged cutout is easy to
// miss until it's live.
TEST_F(DecalBuildTest, MaskWithoutAlphaWarnsButStillAttaches) {
    auto f = file_with_two_named_shapes();
    auto mask = write_tga_no_alpha("mask.tga");

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

    testing::internal::CaptureStderr();
    auto model = assets::detail::build_model(f, ctx);
    const std::string err = testing::internal::GetCapturedStderr();

    ASSERT_TRUE(model.materials[0].decal.enabled)
        << "a mask with no alpha is still attached (treated as opaque)";
    EXPECT_NE(err.find("no alpha channel"), std::string::npos) << err;
    EXPECT_NE(err.find(mask.string()), std::string::npos) << err;
}
