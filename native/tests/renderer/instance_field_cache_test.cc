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
//
// GL_PACK_ALIGNMENT defaults to 4: without overriding it, glGetTexImage pads
// each row out to a multiple of 4 bytes in the destination buffer, so a
// width not itself a multiple of 4 (e.g. 7, from a 5-wide field's 1-texel
// border) reads back with a spurious zero byte at the end of every row --
// this file's earlier fields (dims 4x4x4, atlas width 12) never exposed it
// because 12 already is a multiple of 4. upload() sets the matching
// GL_UNPACK_ALIGNMENT for the write side; this mirrors it for the read.
std::vector<std::uint8_t> read_atlas(const InstanceFieldCache::Entry& e) {
    std::vector<std::uint8_t> pixels(
        static_cast<std::size_t>(e.layout.width) *
        static_cast<std::size_t>(e.layout.height));
    GLint prev_pack = 4;
    glGetIntegerv(GL_PACK_ALIGNMENT, &prev_pack);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glBindTexture(GL_TEXTURE_2D, e.tex2d);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RED, GL_UNSIGNED_BYTE, pixels.data());
    glBindTexture(GL_TEXTURE_2D, 0);
    glPixelStorei(GL_PACK_ALIGNMENT, prev_pack);
    return pixels;
}

constexpr float kAuthoredRes = 10.0f;
const glm::vec3 kUp(0.0f, 0.0f, 1.0f);

// hull_carve_deposit derives its VISIBLE radius from accumulated strength via
// scenegraph::hull_carve_strength_to_radius_gu, in GAME UNITS, then multiplies
// by the caller's inv_scale to reach model units (mirroring host_bindings.cc's
// hull_carve_add: `vis_model = vis_gu * inv_s`). At strength ==
// kHullCarveStrengthIso + 50 that curve gives exactly 0.06 GU
// (kHullCarveRadiusAtIso 0.03 + 50 * kHullCarveRadiusPerStrength 0.0006).
// This inv_scale turns that into model-unit radius 3.0 -- the exact
// radius/cell-10 combination already established elsewhere in this file
// (see TwoInstancesOfSameHullGetIndependentFields) to touch exactly one
// 10-unit cell and no more. Passing inv_scale=1 here (i.e. treating the GU
// curve's output as already model units) was tried first and produced a
// carve too small to round to a visibly-outside cell against this file's
// scale=1.0 fields -- every affected cell quantized to exactly the surface
// (0), not outside it.
constexpr float kInvScaleForRadius3 = 3.0f / 0.06f;

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

// ── hull-volume-field-transport Task 6: wiring carves into the field ───────
//
// The three tests below drive renderer::hull_carve_deposit -- the exact
// function host_bindings.cc's hull_carve_add pybind binding calls, not a
// re-implementation of its arithmetic (see instance_field_cache.h). That
// closes the gap a hand-rolled "simulate what hull_carve_add does" test
// would leave open: if hull_carve_deposit's own body regressed (wrong
// radius passed to the field, or the field carve call dropped entirely),
// these tests fail for that reason. host_bindings.cc's own glue around it --
// the world->body transform, resolve_model, and the pybind argument
// marshalling -- is pybind-only and cannot link into this gtest binary, so
// that thin remainder is verified by direct code reading only.

TEST_F(InstanceFieldCacheTest, ProductionDepositAppearsInBothSphereAndInstanceField) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_dual_deposit");
    const auto src = make_source("hull_dual_deposit.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    scenegraph::HullCarveField sphere_field;
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    const glm::vec3 center_body(5.0f, 5.0f, 5.0f);

    // Strength above the iso so the carve is actually visible (radius > 0) --
    // a sub-iso deposit stays invisible by design and would make this test
    // pass vacuously (an inert 0-radius field carve is a no-op).
    const float strength = scenegraph::kHullCarveStrengthIso + 50.0f;
    const renderer::HullCarveDepositResult result = renderer::hull_carve_deposit(
        sphere_field, &cache, id, src, kAuthoredRes,
        center_body, kUp, /*influ_radius_model=*/3.0f, strength,
        /*floor_radius_model=*/0.0f, /*radius_modifier=*/1.0f,
        /*inv_scale=*/kInvScaleForRadius3);

    ASSERT_GT(result.radius, 0.0f) << "sanity: strength was set above the iso";
    EXPECT_GT(result.radius, result.prev_radius);

    // Sphere side: the same surface the breach scoop / framework lattice /
    // breach-event ring still read.
    ASSERT_EQ(sphere_field.count(), 1u);
    EXPECT_EQ(sphere_field.slots()[0].center_body, center_body);
    EXPECT_FLOAT_EQ(sphere_field.slots()[0].radius, result.radius);

    // Field side: an entry now exists AND actually carries the carve -- not
    // merely "an entry exists" (the untouched-baked-field trap the earlier
    // tests in this file guard against).
    const InstanceFieldCache::Entry* e = cache.get(id);
    ASSERT_NE(e, nullptr);
    voxel::DistanceField expected = baked;
    voxel::field_carve_oblate(expected, center_body, kUp, result.radius);
    const auto expected_bytes = voxel::pack_field_to_atlas(
        expected, voxel::atlas_layout_for(expected.dims));
    const auto baked_bytes = voxel::pack_field_to_atlas(
        baked, voxel::atlas_layout_for(baked.dims));
    ASSERT_NE(expected_bytes, baked_bytes)
        << "sanity: the carve must actually change something";
    EXPECT_EQ(read_atlas(*e), expected_bytes)
        << "the instance field must carry the SAME carve the sphere just "
           "received -- same body-frame centre, normal, and radius";
}

// Behaviour: THE plan's headline win. The sphere ring is a fixed 24-slot
// array (accumulate-merge-then-evict); the field has no such ceiling. 30
// well-separated deposits must evict 6 spheres from the ring while every one
// of the 30 carved cells survives in the field.
TEST_F(InstanceFieldCacheTest, ThirtyCarvesAllSurviveInTheField) {
    // A 5x6 grid of 10-unit cells in the z=0 layer -- 30 distinct cells. A
    // radius-3 carve on a 10-unit cell touches ONLY that one cell (see the
    // arithmetic worked out in TwoInstancesOfSameHullGetIndependentFields
    // above), so every carve below is guaranteed non-overlapping with every
    // other.
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_thirty_carves");
    const auto src = make_source("hull_thirty_carves.nif", "hull");
    voxel::DistanceField baked;
    baked.dims   = glm::ivec3(5, 6, 1);
    baked.origin = glm::vec3(0.0f);
    baked.cell   = glm::vec3(10.0f);
    baked.scale  = 1.0f;
    baked.dist.assign(static_cast<std::size_t>(5 * 6 * 1),
                      static_cast<std::int8_t>(-100));
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    scenegraph::HullCarveField sphere_field;
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    const float strength = scenegraph::kHullCarveStrengthIso + 50.0f;

    std::vector<glm::vec3> centers;
    for (int j = 0; j < 6; ++j) {
        for (int i = 0; i < 5; ++i) {
            centers.emplace_back(i * 10.0f + 5.0f, j * 10.0f + 5.0f, 5.0f);
        }
    }
    ASSERT_EQ(centers.size(), 30u);

    // Independently-built expectation: apply the SAME oblate brush the
    // production carve uses, at every one of the 30 centres, to a private
    // copy of the baked field -- built by this test, not read back from the
    // cache under test.
    voxel::DistanceField expected = baked;
    for (const glm::vec3& c : centers) {
        const renderer::HullCarveDepositResult result = renderer::hull_carve_deposit(
            sphere_field, &cache, id, src, kAuthoredRes, c, kUp,
            /*influ_radius_model=*/1.0f, strength,
            /*floor_radius_model=*/0.0f, /*radius_modifier=*/1.0f,
            /*inv_scale=*/kInvScaleForRadius3);
        ASSERT_GT(result.radius, 0.0f);
        voxel::field_carve_oblate(expected, c, kUp, result.radius);
    }

    // The sphere ring is fixed-capacity: 30 deposits into 24 slots must have
    // evicted six. This is the CURRENT, pre-field behaviour this plan is
    // measured against -- a dying ship's damage popping in and out.
    EXPECT_EQ(sphere_field.count(), scenegraph::HullCarveField::kMaxCarves);

    // Sanity check on the independently-built `expected` field ITSELF (not
    // the cache under test): proves this test's own construction actually
    // touched all 30 cells, so the byte-equality below is not comparing two
    // equally-untouched arrays.
    const auto baked_bytes = voxel::pack_field_to_atlas(
        baked, voxel::atlas_layout_for(baked.dims));
    const auto expected_bytes = voxel::pack_field_to_atlas(
        expected, voxel::atlas_layout_for(expected.dims));
    ASSERT_NE(expected_bytes, baked_bytes);
    for (int j = 0; j < 6; ++j) {
        for (int i = 0; i < 5; ++i) {
            EXPECT_GT(expected.distance_at(i, j, 0), 0.0f)
                << "this test's own reference construction should have "
                   "carved cell (" << i << "," << j << ")";
        }
    }

    // The field has NO 24-slot ceiling: every one of the 30 carved cells,
    // INCLUDING the six the sphere ring evicted, must survive here. This is
    // the assertion that actually distinguishes a working field-carve wire-up
    // from a broken one: if hull_carve_deposit stopped calling
    // field_cache->carve, cache.get(id) would be null after the very first
    // deposit and this ASSERT would fail outright; if it only carved some of
    // the 30, the byte-for-byte compare below would catch the mismatch.
    const InstanceFieldCache::Entry* e = cache.get(id);
    ASSERT_NE(e, nullptr);
    EXPECT_EQ(read_atlas(*e), expected_bytes)
        << "all 30 carves must survive in the field even though the sphere "
           "ring evicted 6 of them";
}

// Behaviour: an instance destroyed and recreated does not inherit the old
// instance's field. scenegraph::World bumps the slot generation on every
// reuse of a freed index (world.cc's create_instance), so "the same id" in
// the practical, player-facing sense used here means "the same slot index" --
// the InstanceId itself always differs afterward. host_bindings.cc's
// destroy_instance binding calls InstanceFieldCache::forget(old_id) at
// exactly the moment the old instance dies, before its index can be
// recycled; this test drives that exact sequence directly (forget() is
// itself production code, just not reachable from this gtest binary via the
// pybind binding around it).
TEST_F(InstanceFieldCacheTest, DestroyedAndRecreatedInstanceDoesNotInheritOldField) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_recycle");
    const auto src = make_source("hull_recycle.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    InstanceFieldCache cache(&bake_cache);
    const float strength = scenegraph::kHullCarveStrengthIso + 50.0f;

    // Old instance: index 1, generation 1 (World's first-ever id at a fresh
    // index). Carve it at cell (0,0,0)'s midpoint.
    scenegraph::HullCarveField old_sphere_field;
    const scenegraph::InstanceId old_id{1, 1};
    renderer::hull_carve_deposit(old_sphere_field, &cache, old_id, src,
                                 kAuthoredRes, glm::vec3(5.0f, 5.0f, 5.0f),
                                 kUp, 3.0f, strength, 0.0f, 1.0f,
                                 kInvScaleForRadius3);

    const InstanceFieldCache::Entry* old_entry = cache.get(old_id);
    ASSERT_NE(old_entry, nullptr);
    const unsigned int old_tex = old_entry->tex2d;
    ASSERT_TRUE(glIsTexture(old_tex));

    // The ship is destroyed: host_bindings.cc's destroy_instance calls
    // forget() at exactly this point.
    cache.forget(old_id);

    // Resource hygiene: forget() at destroy time actually released the OLD
    // texture -- it did not just become unreachable and leak. Checked HERE,
    // before anything else runs, because a texture name freed by
    // glDeleteTextures is eligible for immediate reuse by the very next
    // glGenTextures -- the new instance's own upload() below could otherwise
    // recycle this exact id and make glIsTexture(old_tex) read true again
    // for an unrelated reason, masking a real leak.
    EXPECT_FALSE(glIsTexture(old_tex))
        << "forget() at destroy time must release the old GL texture, not "
           "leak one every time a damaged ship is destroyed and replaced";

    // A new ship spawns and World recycles the same slot INDEX with a
    // bumped generation (world.cc's create_instance: `slots_[idx].generation
    // += 1`). Carve it at cell (3,3,3)'s midpoint -- a different cell from
    // the old instance's carve.
    const scenegraph::InstanceId new_id{1, 2};
    scenegraph::HullCarveField new_sphere_field;
    const renderer::HullCarveDepositResult new_result = renderer::hull_carve_deposit(
        new_sphere_field, &cache, new_id, src, kAuthoredRes,
        glm::vec3(35.0f, 35.0f, 35.0f), kUp, 3.0f, strength, 0.0f, 1.0f,
        kInvScaleForRadius3);
    ASSERT_GT(new_result.radius, 0.0f);

    const InstanceFieldCache::Entry* new_entry = cache.get(new_id);
    ASSERT_NE(new_entry, nullptr);

    // Correctness: the new instance's field reflects ONLY its own carve --
    // freshly copied from the baked field, not the old instance's
    // battle-scarred copy.
    voxel::DistanceField expected_new = baked;
    voxel::field_carve_oblate(expected_new, glm::vec3(35.0f, 35.0f, 35.0f),
                              kUp, new_result.radius);
    const auto expected_new_bytes = voxel::pack_field_to_atlas(
        expected_new, voxel::atlas_layout_for(expected_new.dims));
    EXPECT_EQ(read_atlas(*new_entry), expected_new_bytes)
        << "the new instance must not inherit the old instance's carve";
}

// Behaviour: a MERGED deposit carves the field at the SLOT's stored centre,
// not at the raw point the second hit landed on. HullCarveField::add
// deliberately does not move a slot's centre/normal when a later hit merges
// into it (a swept beam gouges a line, not one carve dragged to the newest
// point -- hull_carve.cc:15-20); hull_carve_deposit must read that merged
// slot back and carve the field at ITS centre, not at this call's raw
// center_body argument.
//
// Discrimination: the FIRST deposit's call-site centre and the slot's stored
// centre are IDENTICAL (a fresh slot always takes the deposit's own
// geometry), so a test with only one deposit -- or two deposits far enough
// apart to land in separate slots -- cannot distinguish "carve at the slot's
// centre" from "carve at this call's raw centre": they agree. This test
// forces two deposits into the SAME slot (B is within merge distance of A)
// at DIFFERENT, well-separated grid cells, so the two candidate carve
// centres are geometrically distinguishable. Reverting the fix (passing
// center_body/normal_body instead of c.center_body/c.surface_normal at
// instance_field_cache.cc's field_cache->carve call) makes this test fail:
// see the task report for the RED transcript.
TEST_F(InstanceFieldCacheTest, MergedDepositCarvesTheFieldAtTheSlotsStoredCentreNotTheRawHitPoint) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_merge_anchor");
    const auto src = make_source("hull_merge_anchor.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));

    // A sits in cell (0,0,0); B sits in cell (3,0,0) of the 4x4x4/cell-10
    // baked field -- 30 units apart, far enough that even a generously
    // oversized (post-merge) carve at one cannot reach the other's cell (see
    // the arithmetic below). influ_radius_model is set large enough that
    // HullCarveField::add's merge_dist (0.5 * influ_radius_model) exceeds
    // that 30-unit separation, so the second deposit MERGES into the first
    // slot instead of opening a new one.
    const glm::vec3 a(5.0f, 5.0f, 5.0f);
    const glm::vec3 b(35.0f, 5.0f, 5.0f);
    const float influ_radius_model = 70.0f;   // merge_dist = 35 > |a-b| = 30
    const float per_deposit_strength = scenegraph::kHullCarveStrengthIso + 50.0f;

    scenegraph::HullCarveField sphere_field;
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};

    const renderer::HullCarveDepositResult first = renderer::hull_carve_deposit(
        sphere_field, &cache, id, src, kAuthoredRes, a, kUp,
        influ_radius_model, per_deposit_strength,
        /*floor_radius_model=*/0.0f, /*radius_modifier=*/1.0f,
        kInvScaleForRadius3);
    ASSERT_GT(first.radius, 0.0f);
    // Radius from a single deposit is small (see kInvScaleForRadius3's
    // derivation) -- an AABB of [a-r, a+r] stays well inside cell (0,0,0)
    // and nowhere near b's cell.
    ASSERT_LT(first.radius, 5.0f);

    const renderer::HullCarveDepositResult second = renderer::hull_carve_deposit(
        sphere_field, &cache, id, src, kAuthoredRes, b, kUp,
        influ_radius_model, per_deposit_strength,
        /*floor_radius_model=*/0.0f, /*radius_modifier=*/1.0f,
        kInvScaleForRadius3);

    // Sanity: this really did merge into the SAME slot (not open a second
    // one), and the slot's stored centre/normal stayed anchored at `a` --
    // exactly the HullCarveField::add contract this test exists to exercise.
    ASSERT_EQ(sphere_field.count(), 1u)
        << "b should have merged into a's slot, not opened a new one";
    EXPECT_EQ(sphere_field.slots()[0].center_body, a)
        << "a merged deposit must not move the slot's centre to the newest "
           "hit point";
    // The merge grew accumulated strength, so the second radius must be
    // bigger than the first -- and still small enough that even a carve
    // anchored at `a` cannot reach b's cell (30 units away).
    EXPECT_GT(second.radius, first.radius);
    ASSERT_LT(second.radius, 15.0f);

    const InstanceFieldCache::Entry* e = cache.get(id);
    ASSERT_NE(e, nullptr);

    // Independently-built expectation: BOTH deposits landed on the SAME
    // slot, so a correct implementation carves the field at `a` twice (first
    // at first.radius, then again at the grown second.radius) -- never at
    // `b`.
    voxel::DistanceField expected = baked;
    voxel::field_carve_oblate(expected, a, kUp, first.radius);
    voxel::field_carve_oblate(expected, a, kUp, second.radius);
    const auto expected_bytes = voxel::pack_field_to_atlas(
        expected, voxel::atlas_layout_for(expected.dims));

    // Sanity: the reference construction actually changed something, and b's
    // cell specifically stayed at the untouched baked value -- otherwise
    // this test could pass vacuously regardless of where the real
    // implementation carved.
    const auto baked_bytes = voxel::pack_field_to_atlas(
        baked, voxel::atlas_layout_for(baked.dims));
    ASSERT_NE(expected_bytes, baked_bytes);
    ASSERT_FLOAT_EQ(expected.distance_at(3, 0, 0), baked.distance_at(3, 0, 0))
        << "sanity: b's cell must stay untouched in the reference "
           "construction too, or this test cannot discriminate";

    EXPECT_EQ(read_atlas(*e), expected_bytes)
        << "a merged deposit must carve the field at the SLOT's stored "
           "centre (a), not at the raw hit point of the call that merged "
           "into it (b)";

}

}  // namespace
