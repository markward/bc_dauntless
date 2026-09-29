// native/tests/assets/cpu/decal_override_test.cc
//
// Per-instance decal override (spec 2026-09-28-spv-decal-editing-design.md
// §2.5): build_decal_override turns a set_instance_decals request list into
// the list the opaque pass draws INSTEAD of Model::decals, with its own
// per-mesh enable masks and GL mask ids. DecalMaskCache is the host-side
// once-per-path mask loader it resolves through. No GL: masks resolve through
// a lambda / a stub uploader.
#include <gtest/gtest.h>

#include <assets/decal_override.h>
#include <assets/model.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
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

// Three GL-free meshes named "a", "b", "a" (a shape can yield several
// meshes). vao 0 => the destructor deletes nothing.
assets::Model model_with_shapes() {
    assets::Model m;
    for (const char* name : {"a", "b", "a"}) {
        assets::Mesh mesh(0, 0, 0, 3, -1, 0);
        mesh.set_shape_name(name);
        m.meshes.push_back(std::move(mesh));
    }
    return m;
}

assets::DecalRequest request(const std::string& shape, const std::string& mask) {
    assets::DecalRequest r;
    r.shape = shape;
    r.origin = {1.0f, 2.0f, 3.0f};
    r.u_axis = {2.0f, 0.0f, 0.0f};
    r.v_axis = {0.0f, -4.0f, 0.0f};
    r.normal = {0.0f, 0.0f, 1.0f};
    r.depth = 0.5f;
    r.mask = mask;
    return r;
}

// Every path resolves to a distinct non-zero id, except "missing.png".
std::uint32_t fake_ids(const fs::path& p) {
    if (p == "missing.png") return 0;
    return 100u + static_cast<std::uint32_t>(p.string().size());
}

}  // namespace

TEST(DecalOverrideTest, ShapeRestrictsTheEnableMaskPerMesh) {
    const auto model = model_with_shapes();
    const auto ov = assets::build_decal_override(
        model, {request("a", "x.png"), request("", "yy.png")}, fake_ids);

    ASSERT_EQ(ov.decals.size(), 2u);
    ASSERT_EQ(ov.mesh_masks.size(), 3u);
    // decal 0 (shape "a") paints meshes 0 and 2; decal 1 (no shape) all.
    EXPECT_EQ(ov.mesh_masks[0], 0x3);
    EXPECT_EQ(ov.mesh_masks[1], 0x2);
    EXPECT_EQ(ov.mesh_masks[2], 0x3);
}

TEST(DecalOverrideTest, DecalGeometryAndTextureIdsMatchTheBakedPath) {
    const auto model = model_with_shapes();
    const auto ov = assets::build_decal_override(
        model, {request("", "x.png")}, fake_ids);

    ASSERT_EQ(ov.decals.size(), 1u);
    const auto& d = ov.decals[0];
    ASSERT_GE(d.mask_slot, 0);
    ASSERT_LT(d.mask_slot, static_cast<int>(ov.texture_ids.size()));
    EXPECT_EQ(ov.texture_ids[static_cast<std::size_t>(d.mask_slot)],
              fake_ids("x.png"));
    // origin -> mask (0,0,0); origin + u_axis -> (1,0,0); origin + v_axis -> (0,1,0).
    const glm::vec4 o = d.body_to_mask * glm::vec4(1.0f, 2.0f, 3.0f, 1.0f);
    const glm::vec4 u = d.body_to_mask * glm::vec4(3.0f, 2.0f, 3.0f, 1.0f);
    const glm::vec4 v = d.body_to_mask * glm::vec4(1.0f, -2.0f, 3.0f, 1.0f);
    EXPECT_NEAR(o.x, 0.0f, 1e-5f); EXPECT_NEAR(o.y, 0.0f, 1e-5f);
    EXPECT_NEAR(u.x, 1.0f, 1e-5f); EXPECT_NEAR(u.y, 0.0f, 1e-5f);
    EXPECT_NEAR(v.x, 0.0f, 1e-5f); EXPECT_NEAR(v.y, 1.0f, 1e-5f);
    EXPECT_FLOAT_EQ(d.depth, 0.5f);
    EXPECT_FLOAT_EQ(d.normal.z, 1.0f);
}

// Unknown shape, degenerate projector and a mask that fails to load each
// skip only their own entry; the survivors are packed so bit i still means
// decals[i].
TEST(DecalOverrideTest, BadEntriesAreSkippedAndSurvivorsPacked) {
    const auto model = model_with_shapes();
    auto degenerate = request("", "d.png");
    degenerate.v_axis = degenerate.u_axis;  // parallel axes
    const auto ov = assets::build_decal_override(
        model,
        {request("nope", "n.png"), degenerate, request("", "missing.png"),
         request("b", "bbbb.png")},
        fake_ids);

    ASSERT_EQ(ov.decals.size(), 1u);
    EXPECT_EQ(ov.texture_ids[static_cast<std::size_t>(ov.decals[0].mask_slot)],
              fake_ids("bbbb.png"));
    EXPECT_EQ(ov.texture_ids.size(), 1u) << "a skipped entry takes no mask slot";
    ASSERT_EQ(ov.mesh_masks.size(), 3u);
    EXPECT_EQ(ov.mesh_masks[0], 0x0);
    EXPECT_EQ(ov.mesh_masks[1], 0x1);
    EXPECT_EQ(ov.mesh_masks[2], 0x0);
}

// 20 entries sharing two masks: the first 16 are kept (spec §2.4a).
TEST(DecalOverrideTest, AtMostSixteenDecals) {
    const auto model = model_with_shapes();
    std::vector<assets::DecalRequest> reqs;
    for (int i = 0; i < 20; ++i) reqs.push_back(request("", i % 2 ? "m1" : "m0"));
    const auto ov = assets::build_decal_override(model, reqs, fake_ids);
    EXPECT_EQ(assets::kMaxDecals, 16);
    EXPECT_EQ(ov.decals.size(), 16u);
    EXPECT_EQ(ov.texture_ids.size(), 2u);
}

// Review Focus 1, override side: entries naming the same mask resolve it
// ONCE and share its slot.
TEST(DecalOverrideTest, SharedMaskResolvesOnceAndSharesASlot) {
    const auto model = model_with_shapes();
    int resolves = 0;
    const auto ov = assets::build_decal_override(
        model,
        {request("a", "shared.png"), request("", "other.png"),
         request("b", "shared.png"), request("", "./shared.png")},
        [&](const fs::path& p) { ++resolves; return fake_ids(p); });

    ASSERT_EQ(ov.decals.size(), 4u);
    EXPECT_EQ(resolves, 2) << "each distinct mask resolves once";
    ASSERT_EQ(ov.texture_ids.size(), 2u);
    EXPECT_EQ(ov.decals[0].mask_slot, 0);
    EXPECT_EQ(ov.decals[1].mask_slot, 1);
    EXPECT_EQ(ov.decals[2].mask_slot, 0);
    EXPECT_EQ(ov.decals[3].mask_slot, 0);
}

// Review Focus 2, override side: a 5th distinct mask skips its entry
// without even resolving it (a resolve would load -- and possibly retire --
// a texture for nothing); a later entry reusing a slot still attaches.
TEST(DecalOverrideTest, FifthDistinctMaskIsSkippedUnresolved) {
    const auto model = model_with_shapes();
    std::vector<assets::DecalRequest> reqs;
    for (int i = 0; i < 6; ++i) reqs.push_back(request("", "m" + std::to_string(i)));
    reqs.push_back(request("", "m2"));
    std::vector<fs::path> resolved;
    const auto ov = assets::build_decal_override(
        model, reqs,
        [&](const fs::path& p) { resolved.push_back(p); return fake_ids(p); });

    EXPECT_EQ(assets::kMaxDecalMasks, 4);
    ASSERT_EQ(ov.decals.size(), 5u);
    EXPECT_EQ(ov.texture_ids.size(), 4u);
    EXPECT_EQ(resolved.size(), 4u);
    EXPECT_EQ(ov.decals[4].mask_slot, 2);
}

// Review Focus 3, override side: 16-bit per-mesh enable masks.
TEST(DecalOverrideTest, ShapeRestrictionWorksAboveBitThree) {
    const auto model = model_with_shapes();
    std::vector<assets::DecalRequest> reqs(16, request("", "x.png"));
    reqs[10].shape = "b";
    const auto ov = assets::build_decal_override(model, reqs, fake_ids);
    ASSERT_EQ(ov.decals.size(), 16u);
    ASSERT_EQ(ov.mesh_masks.size(), 3u);
    const unsigned bit10 = 1u << 10;
    EXPECT_EQ(ov.mesh_masks[0], 0xFFFFu & ~bit10);
    EXPECT_EQ(ov.mesh_masks[1], 0xFFFFu);
    EXPECT_EQ(ov.mesh_masks[2], 0xFFFFu & ~bit10);
}

TEST(DecalOverrideTest, EmptyListIsAnEmptyOverride) {
    const auto model = model_with_shapes();
    const auto ov = assets::build_decal_override(model, {}, fake_ids);
    EXPECT_TRUE(ov.decals.empty());
    ASSERT_EQ(ov.mesh_masks.size(), 3u);
    for (auto m : ov.mesh_masks) EXPECT_EQ(m, 0x0);
}

// ── DecalMaskCache ─────────────────────────────────────────────────────────

namespace {

// 2x1 RGBA PNG (decal_build_test.cc's bytes). Pixel 0: opaque red. Pixel 1:
// half-transparent blue.
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

class DecalMaskCacheTest : public ::testing::Test {
protected:
    fs::path tmp_dir;
    std::vector<assets::Image> uploaded;
    std::vector<bool> mipmapped;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "decal-mask-cache";
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

    // id 0 keeps the Texture destructor GL-free.
    assets::DecalMaskCache make_cache() {
        return assets::DecalMaskCache(
            [this](const assets::Image& img, bool mips) {
                uploaded.push_back(img);
                mipmapped.push_back(mips);
                return assets::Texture(0, img.width, img.height, mips);
            });
    }
};

}  // namespace

TEST_F(DecalMaskCacheTest, LoadsEachPathOncePremultipliedAndMipmapped) {
    auto cache = make_cache();
    const auto path = write_png("mask.png");
    cache.get(path);
    cache.get(path);

    ASSERT_EQ(uploaded.size(), 1u) << "a path must upload once";
    EXPECT_EQ(cache.size(), 1u);
    EXPECT_TRUE(mipmapped[0]);
    const auto& img = uploaded[0];
    ASSERT_EQ(img.format, assets::Image::Format::RGBA8);
    ASSERT_EQ(img.pixels.size(), 8u);
    // Opaque red unchanged; half-transparent blue premultiplied: B = 255*a/255.
    EXPECT_EQ(img.pixels[0], 255);
    const unsigned a = img.pixels[7];
    EXPECT_LT(a, 255u);
    EXPECT_EQ(img.pixels[6], static_cast<std::uint8_t>((255u * a + 127u) / 255u));
}

TEST_F(DecalMaskCacheTest, MissingFileResolvesToZeroAndIsNotCached) {
    auto cache = make_cache();
    EXPECT_EQ(cache.get(tmp_dir / "nope.png"), 0u);
    EXPECT_EQ(cache.size(), 0u);
    EXPECT_TRUE(uploaded.empty());
}

TEST_F(DecalMaskCacheTest, ClearReleasesEverything) {
    auto cache = make_cache();
    cache.get(write_png("a.png"));
    cache.get(write_png("b.png"));
    EXPECT_EQ(cache.size(), 2u);
    cache.clear();
    EXPECT_EQ(cache.size(), 0u);
}

// The SPV previews a placement with no registry PNG through this committed
// project asset. It must load through the SAME cache path a real mask does
// (decode_image, premultiplied): a 64x32 checker at 50% alpha.
TEST_F(DecalMaskCacheTest, TheCommittedPlaceholderLoadsAsA64x32HalfAlphaMask) {
    auto cache = make_cache();
    const fs::path placeholder = fs::path(OPEN_STBC_PROJECT_ROOT) /
        "native" / "assets" / "textures" / "decal_placeholder.png";
    cache.get(placeholder);
    ASSERT_EQ(uploaded.size(), 1u) << placeholder;
    const auto& img = uploaded[0];
    EXPECT_EQ(img.width, 64u);
    EXPECT_EQ(img.height, 32u);
    ASSERT_EQ(img.format, assets::Image::Format::RGBA8);
    EXPECT_EQ(img.pixels[3], 128u);
}

// Ruling K: Mark re-exports a mask from Gimp while the SPV is open, and the
// next set_instance_decals must show it -- a path whose file mtime changed
// since it was cached is decoded and uploaded again; an unchanged one is not.
TEST_F(DecalMaskCacheTest, ReloadsAPathWhoseFileMtimeChanged) {
    auto cache = make_cache();
    const auto path = write_png("mask.png");
    cache.get(path);
    cache.get(path);
    ASSERT_EQ(uploaded.size(), 1u);

    fs::last_write_time(path, fs::last_write_time(path) + std::chrono::seconds(5));
    cache.get(path);
    EXPECT_EQ(uploaded.size(), 2u) << "a re-exported mask must reload";
    EXPECT_EQ(cache.size(), 1u) << "still one live entry per path";

    cache.get(path);
    EXPECT_EQ(uploaded.size(), 2u) << "and only once per change";
}

// Fix round 1 (M3): every reload retires the superseded texture, and Mark may
// re-export a mask hundreds of times in one session -- the retired list is
// capped, dropping the oldest, so it cannot grow without bound.
TEST_F(DecalMaskCacheTest, RetiredTexturesAreCapped) {
    auto cache = make_cache();
    const auto path = write_png("mask.png");
    cache.get(path);
    auto t = fs::last_write_time(path);
    for (int i = 1; i <= 50; ++i) {
        fs::last_write_time(path, t + std::chrono::seconds(i));
        cache.get(path);
    }
    EXPECT_EQ(uploaded.size(), 51u);
    EXPECT_EQ(cache.size(), 1u);
    EXPECT_LE(cache.retired_count(), assets::DecalMaskCache::kMaxRetired);
    EXPECT_GT(assets::DecalMaskCache::kMaxRetired, 0u);
}
