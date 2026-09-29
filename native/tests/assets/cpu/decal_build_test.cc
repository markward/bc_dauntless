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

    // A valid request on `shape` ("" = every mesh) using `mask`.
    static assets::DecalRequest request(const std::string& shape,
                                        const fs::path& mask) {
        assets::DecalRequest req;
        req.shape = shape;
        req.origin = {0.0f, 0.0f, 0.0f};
        req.u_axis = {1.0f, 0.0f, 0.0f};
        req.v_axis = {0.0f, 1.0f, 0.0f};
        req.normal = {0.0f, 0.0f, 1.0f};
        req.depth = 2.0f;
        req.mask = mask;
        return req;
    }

    // Index of the mesh built from the shape named `name` (-1 if none).
    static int mesh_for_shape(const assets::Model& m, const std::string& name) {
        for (std::size_t i = 0; i < m.meshes.size(); ++i)
            if (m.meshes[i].shape_name() == name) return static_cast<int>(i);
        return -1;
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
    ctx.decals = {request("a", mask)};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 1u);
    const auto& d = model.decals[0];
    ASSERT_EQ(d.mask_slot, 0);
    ASSERT_EQ(model.decal_masks.size(), 1u);
    ASSERT_GE(model.decal_masks[0], 0);
    ASSERT_LT(model.decal_masks[0], static_cast<int>(model.textures.size()));
    EXPECT_FLOAT_EQ(d.depth, 2.0f);
    EXPECT_NEAR(glm::length(d.normal), 1.0f, 1e-5f);

    const int a = mesh_for_shape(model, "a");
    const int b = mesh_for_shape(model, "b");
    ASSERT_GE(a, 0);
    ASSERT_GE(b, 0);
    EXPECT_NE(model.meshes[a].decal_mask() & 0x1, 0);
    EXPECT_EQ(model.meshes[b].decal_mask() & 0x1, 0);
}

// (a) Two requests: `top` restricted to shape "a", `bottom` with no shape.
// Both attach, in request order; bit 0 is set only on "a"'s mesh, bit 1 on
// every mesh.
TEST_F(DecalBuildTest, ShapeIsOptionalAndSetsPerMeshBits) {
    auto f = file_with_two_named_shapes();
    auto top = write_png("top.png");
    auto bottom = write_png("bottom.png");

    auto ctx = make_ctx();
    auto bottom_req = request("", bottom);
    bottom_req.normal = {0.0f, 0.0f, -1.0f};
    ctx.decals = {request("a", top), bottom_req};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 2u);
    EXPECT_NEAR(model.decals[0].normal.z, 1.0f, 1e-5f);
    EXPECT_NEAR(model.decals[1].normal.z, -1.0f, 1e-5f);
    EXPECT_NE(model.decals[0].mask_slot, model.decals[1].mask_slot);
    EXPECT_EQ(model.decal_masks.size(), 2u);

    const int a = mesh_for_shape(model, "a");
    const int b = mesh_for_shape(model, "b");
    ASSERT_GE(a, 0);
    ASSERT_GE(b, 0);
    EXPECT_NE(model.meshes[a].decal_mask() & 0x1, 0);
    EXPECT_EQ(model.meshes[b].decal_mask() & 0x1, 0);
    EXPECT_NE(model.meshes[a].decal_mask() & 0x2, 0);
    EXPECT_NE(model.meshes[b].decal_mask() & 0x2, 0);
}

// (b) More than kMaxDecals placements: the first sixteen are kept, the
// rest dropped with exactly one warning (spec §2.4a).
TEST_F(DecalBuildTest, SeventeenRequestsKeepSixteenWithOneWarning) {
    auto f = file_with_two_named_shapes();
    f.source = tmp_dir / "seventeen.nif";  // warn-once keys are per model
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    ctx.decals.assign(17, request("", mask));

    testing::internal::CaptureStderr();
    auto model = assets::detail::build_model(f, ctx);
    const std::string err = testing::internal::GetCapturedStderr();

    EXPECT_EQ(assets::kMaxDecals, 16);
    EXPECT_EQ(assets::kMaxDecalMasks, 4);
    EXPECT_EQ(model.decals.size(), 16u);
    std::size_t warnings = 0;
    for (auto pos = err.find("more than 16 decals"); pos != std::string::npos;
         pos = err.find("more than 16 decals", pos + 1))
        ++warnings;
    EXPECT_EQ(warnings, 1u) << err;
}

// Review Focus 1: two placements naming the SAME mask -- even spelled
// differently, since masks dedupe by resolved absolute path -- decode and
// upload it once, and both projectors point at the one slot.
TEST_F(DecalBuildTest, SharedMaskIsUploadedOnceAndBothPlacementsShareASlot) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("shared.png");
    const fs::path same_mask_other_spelling = tmp_dir / "." / "shared.png";

    int uploads = 0;
    auto ctx = make_ctx();
    ctx.texture_uploader = [&uploads](const assets::Image& img, bool mips) {
        ++uploads;
        return stub_texture(img, mips);
    };
    auto second = request("", same_mask_other_spelling);
    second.origin = {5.0f, 0.0f, 0.0f};
    ctx.decals = {request("a", mask), second};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 2u);
    EXPECT_EQ(uploads, 1) << "a shared mask must be decoded and uploaded once";
    ASSERT_EQ(model.decal_masks.size(), 1u);
    EXPECT_EQ(model.decals[0].mask_slot, 0);
    EXPECT_EQ(model.decals[1].mask_slot, 0);
    EXPECT_EQ(model.textures.size(), 1u);
}

// Review Focus 2: five distinct masks -> slots 0..3 are used, the placement
// needing a 5th is skipped (and a 6th distinct one too) with exactly ONE
// warning, and a later placement reusing an existing mask still attaches.
TEST_F(DecalBuildTest, FifthDistinctMaskIsSkippedWithOneWarning) {
    auto f = file_with_two_named_shapes();
    f.source = tmp_dir / "five-masks.nif";  // warn-once keys are per model
    std::vector<fs::path> masks;
    for (int i = 0; i < 6; ++i)
        masks.push_back(write_png("m" + std::to_string(i) + ".png"));

    auto ctx = make_ctx();
    for (int i = 0; i < 6; ++i) ctx.decals.push_back(request("", masks[i]));
    ctx.decals.push_back(request("b", masks[1]));  // reuses slot 1

    testing::internal::CaptureStderr();
    auto model = assets::detail::build_model(f, ctx);
    const std::string err = testing::internal::GetCapturedStderr();

    EXPECT_EQ(model.decal_masks.size(), 4u);
    ASSERT_EQ(model.decals.size(), 5u);
    for (int i = 0; i < 4; ++i) EXPECT_EQ(model.decals[i].mask_slot, i);
    EXPECT_EQ(model.decals[4].mask_slot, 1);
    std::size_t warnings = 0;
    for (auto pos = err.find("more than 4 distinct masks"); pos != std::string::npos;
         pos = err.find("more than 4 distinct masks", pos + 1))
        ++warnings;
    EXPECT_EQ(warnings, 1u) << err;
    EXPECT_NE(err.find(masks[4].string()), std::string::npos) << err;
}

// Review Focus 3: the per-mesh enable mask holds 16 bits -- a decal at index
// 10 restricted to shape "a" is enabled on "a"'s mesh and nowhere else.
TEST_F(DecalBuildTest, ShapeRestrictionWorksAboveBitThree) {
    auto f = file_with_two_named_shapes();
    auto mask = write_png("mask.png");

    auto ctx = make_ctx();
    ctx.decals.assign(16, request("", mask));
    ctx.decals[10].shape = "a";

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 16u);
    const int a = mesh_for_shape(model, "a");
    const int b = mesh_for_shape(model, "b");
    ASSERT_GE(a, 0);
    ASSERT_GE(b, 0);
    const unsigned bit10 = 1u << 10;
    EXPECT_NE(model.meshes[a].decal_mask() & bit10, 0u);
    EXPECT_EQ(model.meshes[b].decal_mask() & bit10, 0u);
    // Every unrestricted decal, below and above bit 10, still paints both.
    EXPECT_EQ(model.meshes[a].decal_mask() & 0xFFFFu, 0xFFFFu);
    EXPECT_EQ(model.meshes[b].decal_mask() & 0xFFFFu, 0xFFFFu & ~bit10);
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
    EXPECT_TRUE(model.decals.empty());
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
    EXPECT_TRUE(model.decals.empty());
}

// Two decals may now share a shape (the old one-decal-per-material ruling
// went with the per-material Decal0 stage): both attach, each with its own
// uploaded mask.
TEST_F(DecalBuildTest, TwoDecalsOnSameShapeBothAttach) {
    auto f = file_with_two_named_shapes();
    auto mask1 = write_png("mask1.png");
    auto mask2 = write_png("mask2.png");

    auto ctx = make_ctx();
    ctx.decals = {request("a", mask1), request("a", mask2)};

    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 2u);
    EXPECT_EQ(model.textures.size(), 2u);
    const int a = mesh_for_shape(model, "a");
    ASSERT_GE(a, 0);
    EXPECT_EQ(model.meshes[a].decal_mask() & 0x3, 0x3);
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
    EXPECT_TRUE(model.decals.empty());
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
    EXPECT_TRUE(model.decals.empty());
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
    EXPECT_TRUE(model.decals.empty());
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

// --- No mesh-fix gate --------------------------------------------------
//
// Decals used to attach only on top of a mesh the fix had patched. That gate
// is gone (spec 2026-09-28-spv-decal-editing-design.md §2.1): decals are an
// independent per-class feature, attached whenever requested. Mesh fixes
// still apply exactly as before.

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

// The SPV edits a placement's GEOMETRY without touching its shape or mask,
// so the cache key must fold origin/axes/normal/depth in exactly: requests
// that differ only in origin are distinct entries, identical ones share one.
TEST(DecalCache, PlacementGeometryIsPartOfTheKey) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    assets::AssetCache cache(stub_config());
    std::vector<fs::path> search{ambassador_high_path()};

    const auto req = top_decal_request(zhukov_top_mask());
    auto moved = req;
    moved.origin.x += 0.5f;

    auto a = cache.load(ambassador_nif_path(), search, {}, {req});
    auto a_again = cache.load(ambassador_nif_path(), search, {}, {req});
    auto b = cache.load(ambassador_nif_path(), search, {}, {moved});
    EXPECT_EQ(a.get(), a_again.get());
    EXPECT_NE(a.get(), b.get());
}

// Real Ambassador + the committed fixes dir + a decal -> attached.
TEST(DecalNoMeshFixGate, AttachedWhenMeshFixApplies) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    auto cfg = stub_config();
    cfg.mesh_fix_dir = [] { return committed_mesh_fixes_dir(); };
    assets::AssetCache cache(cfg);
    auto model = cache.load(ambassador_nif_path(), {ambassador_high_path()}, {},
                             {top_decal_request(zhukov_top_mask())});
    EXPECT_EQ(model->decals.size(), 1u);
}

// (c) No mesh_fix_dir configured at all -> the decal STILL attaches, and no
// "hull decals skipped" warning.
TEST(DecalNoMeshFixGate, AttachedWithoutMeshFixDirConfigured) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    ASSERT_TRUE(fs::exists(zhukov_top_mask())) << zhukov_top_mask();

    assets::AssetCache cache(stub_config());  // no mesh_fix_dir at all
    testing::internal::CaptureStderr();
    auto model = cache.load(ambassador_nif_path(), {ambassador_high_path()}, {},
                             {top_decal_request(zhukov_top_mask())});
    const std::string err = testing::internal::GetCapturedStderr();

    EXPECT_EQ(model->decals.size(), 1u);
    EXPECT_EQ(err.find("hull decals skipped"), std::string::npos) << err;
}

// A fix that is refused -> the mesh loads unpatched, and the decal still
// attaches.
TEST(DecalNoMeshFixGate, AttachedWhenMeshFixIsRefused) {
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

    EXPECT_EQ(model->decals.size(), 1u);
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

    // Build WITH keep_cpu_data (to read the vertices back) and find the
    // mesh built from this shape by its recorded shape name.
    assets::PathResolver path_resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &path_resolver;
    ctx.texture_search_paths = {ambassador_high_path()};
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.keep_cpu_data = true;
    ctx.decals = {top_decal_request(zhukov_top_mask())};
    auto model = assets::detail::build_model(f, ctx);
    ASSERT_EQ(model.decals.size(), 1u) << "decal was not attached";

    const assets::Mesh* mesh = nullptr;
    for (const auto& m : model.meshes) {
        if (m.shape_name() == kShapeName) { mesh = &m; break; }
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
    ASSERT_EQ(model.decals.size(), 1u);
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

    ASSERT_EQ(model.decals.size(), 1u)
        << "a mask with no alpha is still attached (treated as opaque)";
    EXPECT_NE(err.find("no alpha channel"), std::string::npos) << err;
    EXPECT_NE(err.find(mask.string()), std::string::npos) << err;
}
