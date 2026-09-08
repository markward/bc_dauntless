// native/tests/renderer/instance_field_cache_test.cc
//
// renderer::InstanceFieldCache: one mutable signed distance field per
// DAMAGED ship instance, copy-on-first-carve from the shared per-hull baked
// field (voxel::HullVolumeCache), packed into a GL_R8 2D atlas on demand.
//
// Every test constructs its own local voxel::HullVolumeCache and injects it
// via InstanceFieldCache's bake_cache constructor argument, rather than
// touching the process-wide renderer::hull_volume_cache() singleton.
// hull_volume_cache_root_test.cc documents itself as the ONLY caller of that
// singleton in this test binary, specifically so its root-selection test
// stays deterministic regardless of test run order -- a second caller here
// would silently make that test's outcome depend on which TEST happens to
// run first.
//
// GL fixture pattern follows gl_caps_test.cc / carve_cavity_test.cc's
// neighbours: a hidden renderer::Window, GTEST_SKIP on construction failure.

#include <gtest/gtest.h>

#include <renderer/instance_field_cache.h>
#include <renderer/window.h>

#include <voxel/dhv.h>
#include <voxel/field_atlas.h>
#include <voxel/field_brush.h>
#include <voxel/hull_volume_cache.h>

#include <glad/glad.h>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <system_error>
#include <thread>
#include <vector>

namespace {

using renderer::InstanceFieldCache;

// One scratch directory per test-binary PROCESS invocation (not per TEST):
// this checkout is shared by concurrent Claude sessions, so a fixed /tmp path
// would collide across simultaneous `ctest` runs. Mirrors
// native/tests/voxel/hull_volume_cache_test.cc's scratch_root().
std::filesystem::path scratch_root() {
    static const std::filesystem::path root = [] {
        std::ostringstream os;
        os << "dauntless_instance_field_cache_test_"
           << std::hash<std::thread::id>{}(std::this_thread::get_id()) << '_'
           << std::chrono::steady_clock::now().time_since_epoch().count();
        return std::filesystem::temp_directory_path() / os.str();
    }();
    return root;
}

// A source file standing in for a hull NIF: HullVolumeCache fingerprints it
// by size + mtime, never actually parses it in these tests (every field is
// pre-seeded straight into the .dhv cache, bypassing NIF parsing entirely --
// same technique as hull_volume_cache_test.cc's
// ServesAWrittenFieldWithoutRebaking).
std::filesystem::path make_source(const char* name, const char* body) {
    std::filesystem::create_directories(scratch_root());
    const auto p = scratch_root() / name;
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    s << body;
    return p;
}

// A small, fully-inside field: every cell starts at -100 (deep inside, far
// from the surface), so a carve's oblate brush -- which only ever raises a
// cell toward/through zero, never lowers it -- visibly changes whatever
// cells it touches while leaving every other cell exactly at its original
// -100.
voxel::DistanceField make_baked_field() {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(4, 4, 4);
    f.origin = glm::vec3(0.0f);
    f.cell   = glm::vec3(10.0f);
    f.scale  = 1.0f;
    f.dist.assign(static_cast<std::size_t>(4 * 4 * 4),
                  static_cast<std::int8_t>(-100));
    return f;
}

// Pre-populate `cache`'s on-disk entry for (src, authored_res, quality) with
// `field`, using the exact fingerprint HullVolumeCache::get computes itself,
// so the entry validates as current and is served rather than rebaked (which
// would silently discard `field` and serve an empty one, since `src` is not
// a real NIF).
bool seed_baked_field(voxel::HullVolumeCache& cache,
                      const std::filesystem::path& src,
                      float authored_res, float quality,
                      const voxel::DistanceField& field) {
    voxel::HullVolumeMeta meta;
    meta.baker_version = voxel::kBakerVersion;
    std::error_code ec;
    meta.source_size =
        static_cast<std::uint32_t>(std::filesystem::file_size(src, ec));
    if (ec) return false;
    const auto t = std::filesystem::last_write_time(src, ec);
    if (ec) return false;
    meta.source_mtime = static_cast<std::int64_t>(t.time_since_epoch().count());
    meta.authored_res = authored_res;
    meta.quality       = quality;
    meta.source_path   = src.string();
    return voxel::write_dhv(cache.path_for(src, authored_res, quality), field,
                            meta);
}

// Read back the whole GL_R8 atlas actually bound in `e` -- proves what
// InstanceFieldCache uploaded, not just what it recorded in the Entry's
// glm-typed geometry fields.
std::vector<std::uint8_t> read_atlas(const InstanceFieldCache::Entry& e) {
    std::vector<std::uint8_t> pixels(
        static_cast<std::size_t>(e.layout.width) *
        static_cast<std::size_t>(e.layout.height));
    glBindTexture(GL_TEXTURE_2D, e.tex2d);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RED, GL_UNSIGNED_BYTE, pixels.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    return pixels;
}

constexpr float kAuthoredRes = 10.0f;
const glm::vec3 kUp(0.0f, 0.0f, 1.0f);

class InstanceFieldCacheTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(
                64, 64, "instance-field-cache-test", /*visible=*/false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context available: " << e.what();
        }
    }
};

// Behaviour 1: an instance that was never carved has no entry, so an
// undamaged ship costs nothing. carve() is never called for `id` here --
// this exercises the "nothing in the map at all" path, not a carve that
// happened to no-op.
TEST_F(InstanceFieldCacheTest, NeverCarvedInstanceHasNoEntry) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_never_carved");
    InstanceFieldCache cache(&bake_cache);

    const scenegraph::InstanceId id{1, 0};
    EXPECT_EQ(cache.get(id), nullptr);
    EXPECT_EQ(cache.size(), 0u);
}

// Behaviour 2: the first carve creates an entry whose dims/origin/cell match
// the baked field it copied from.
TEST_F(InstanceFieldCacheTest, FirstCarveMatchesBakedGeometry) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_first_carve");
    const auto src = make_source("hull_first_carve.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);

    const InstanceFieldCache::Entry* e = cache.get(id);
    ASSERT_NE(e, nullptr);
    EXPECT_EQ(e->dims, baked.dims);
    EXPECT_EQ(e->origin, baked.origin);
    EXPECT_EQ(e->cell, baked.cell);
    EXPECT_FLOAT_EQ(e->scale, baked.scale);
    EXPECT_EQ(cache.size(), 1u);
}

// Behaviour 3: get() twice without an intervening carve uploads exactly
// once. If get() re-uploaded every call, uploads() would read 2 here and the
// texture object would differ between the two returned pointers -- neither
// happens on a working implementation.
TEST_F(InstanceFieldCacheTest, RepeatedGetWithoutCarveUploadsOnce) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_repeated_get");
    const auto src = make_source("hull_repeated_get.nif", "hull");
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, make_baked_field()));

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);

    const InstanceFieldCache::Entry* first = cache.get(id);
    ASSERT_NE(first, nullptr);
    const unsigned int tex_after_first = first->tex2d;
    EXPECT_EQ(cache.uploads(), 1u);

    const InstanceFieldCache::Entry* second = cache.get(id);
    ASSERT_NE(second, nullptr);
    EXPECT_EQ(cache.uploads(), 1u)
        << "a second get() with no intervening carve must not re-upload";
    EXPECT_EQ(second->tex2d, tex_after_first)
        << "the same GL texture object must be reused, not recreated";
}

// Behaviour 4: a carve marks the instance dirty and the next get()
// re-uploads -- uploads() advances, and the atlas content actually reflects
// the new carve (not merely a bumped counter with stale bytes).
TEST_F(InstanceFieldCacheTest, CarveMarksDirtyAndNextGetReuploads) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_reupload");
    const auto src = make_source("hull_reupload.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);
    const InstanceFieldCache::Entry* e1 = cache.get(id);
    ASSERT_NE(e1, nullptr);
    const auto bytes_after_first_carve = read_atlas(*e1);
    EXPECT_EQ(cache.uploads(), 1u);

    // A second carve at the opposite corner of the grid -- guaranteed to
    // touch cells the first carve did not (see the independence test below
    // for the exact cell arithmetic).
    cache.carve(id, src, kAuthoredRes, glm::vec3(35, 35, 35), kUp, 3.0f);
    const InstanceFieldCache::Entry* e2 = cache.get(id);
    ASSERT_NE(e2, nullptr);
    EXPECT_EQ(cache.uploads(), 2u)
        << "the carve must dirty the entry so the next get() re-uploads";
    const auto bytes_after_second_carve = read_atlas(*e2);
    EXPECT_NE(bytes_after_first_carve, bytes_after_second_carve)
        << "the re-upload must actually carry the second carve's change, "
           "not just bump the counter over stale bytes";
}

// Behaviour 5: forget() releases both the map entry and the GL texture
// object -- checked with glIsTexture, not just "get() now returns null",
// which a leak would pass just as easily.
TEST_F(InstanceFieldCacheTest, ForgetReleasesEntryAndTexture) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_forget");
    const auto src = make_source("hull_forget.nif", "hull");
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, make_baked_field()));

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);
    const InstanceFieldCache::Entry* e = cache.get(id);
    ASSERT_NE(e, nullptr);
    const unsigned int tex = e->tex2d;
    ASSERT_TRUE(glIsTexture(tex));

    cache.forget(id);

    EXPECT_EQ(cache.get(id), nullptr);
    EXPECT_EQ(cache.size(), 0u);
    EXPECT_FALSE(glIsTexture(tex))
        << "forget() must actually delete the GL texture, not just drop the "
           "map entry and leak it";
}

// Behaviour 6: a hull with no baked field (missing/unreadable source) never
// creates an entry -- carve() must be a true no-op, not "create an empty
// entry nobody uploads".
TEST_F(InstanceFieldCacheTest, HullWithNoBakedFieldNeverCreatesEntry) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_no_baked");
    // Never created on disk, and nothing seeded for it in bake_cache: get()
    // inside carve() will find no cache hit and no NIF to bake from, and
    // must serve an empty field.
    const auto missing_src = scratch_root() / "does_not_exist.nif";

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, missing_src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);

    EXPECT_EQ(cache.get(id), nullptr);
    EXPECT_EQ(cache.size(), 0u);
}

// Behaviour 7 -- THE per-instance guarantee: two instances of the SAME hull
// get independent fields. Carving instance A must not leave any trace in
// instance B's field, even though both started as copies of the identical
// baked field.
//
// Discrimination: each instance is carved at a DIFFERENT, non-overlapping
// grid cell (radius 3 against a 10-unit cell means each carve's AABB clips
// to exactly one cell -- see the arithmetic in the comments below). The
// "expected" atlas for each instance is computed independently, in this
// test, by copying the SAME baked field and applying ONLY that instance's
// own carve -- never the other's. If InstanceFieldCache actually shared
// storage between the two instances (the exact bug this test exists to
// catch), instance A's actual bytes would pick up instance B's carve too and
// stop matching the independently-computed "A only" expectation, so a
// broken implementation cannot pass this by accident: an all-untouched
// field would fail the dims/uploads assertions below, and a
// shared-storage field would fail the byte-for-byte comparisons.
TEST_F(InstanceFieldCacheTest, TwoInstancesOfSameHullGetIndependentFields) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_independence");
    const auto src = make_source("hull_independence.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    // dims (4,4,4), cell 10, origin 0: a radius-3 carve's AABB is [c-3,c+3]
    // on every axis. Centred on cell (0,0,0)'s midpoint (5,5,5), that AABB
    // is [2,8] -> cell index floor(0.2)..floor(0.8) = 0..0 on every axis:
    // touches ONLY cell (0,0,0). Centred on cell (3,3,3)'s midpoint
    // (35,35,35), the AABB [32,38] -> floor(3.2)..floor(3.8) = 3..3:
    // touches ONLY cell (3,3,3). The two carves cannot overlap.
    const glm::vec3 p_a(5.0f, 5.0f, 5.0f);
    const glm::vec3 p_b(35.0f, 35.0f, 35.0f);
    const float radius = 3.0f;

    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id_a{1, 0};
    const scenegraph::InstanceId id_b{2, 0};

    cache.carve(id_a, src, kAuthoredRes, p_a, kUp, radius);
    cache.carve(id_b, src, kAuthoredRes, p_b, kUp, radius);

    const InstanceFieldCache::Entry* ea = cache.get(id_a);
    const InstanceFieldCache::Entry* eb = cache.get(id_b);
    ASSERT_NE(ea, nullptr);
    ASSERT_NE(eb, nullptr);
    EXPECT_NE(ea->tex2d, eb->tex2d)
        << "distinct instances must not share one GL texture object";

    // Independently-computed expectations: each starts from the SAME baked
    // field but is carved ONLY at its own instance's location.
    voxel::DistanceField expected_a = baked;
    voxel::field_carve_oblate(expected_a, p_a, kUp, radius);
    const voxel::AtlasLayout layout_a = voxel::atlas_layout_for(expected_a.dims);
    const std::vector<std::uint8_t> expected_a_bytes =
        voxel::pack_field_to_atlas(expected_a, layout_a);

    voxel::DistanceField expected_b = baked;
    voxel::field_carve_oblate(expected_b, p_b, kUp, radius);
    const voxel::AtlasLayout layout_b = voxel::atlas_layout_for(expected_b.dims);
    const std::vector<std::uint8_t> expected_b_bytes =
        voxel::pack_field_to_atlas(expected_b, layout_b);

    // Sanity: the two expectations must actually differ from each other and
    // from the untouched baked field, or this test would pass vacuously no
    // matter what InstanceFieldCache does.
    const std::vector<std::uint8_t> baked_bytes =
        voxel::pack_field_to_atlas(baked, voxel::atlas_layout_for(baked.dims));
    ASSERT_NE(expected_a_bytes, baked_bytes);
    ASSERT_NE(expected_b_bytes, baked_bytes);
    ASSERT_NE(expected_a_bytes, expected_b_bytes);

    EXPECT_EQ(read_atlas(*ea), expected_a_bytes)
        << "instance A must carry exactly its own carve -- not none, and "
           "not instance B's";
    EXPECT_EQ(read_atlas(*eb), expected_b_bytes)
        << "instance B must carry exactly its own carve -- not none, and "
           "not instance A's";
}

}  // namespace
