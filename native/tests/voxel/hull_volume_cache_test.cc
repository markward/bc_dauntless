// native/tests/voxel/hull_volume_cache_test.cc
//
// Bake once, then load. The interesting cases are all invalidation: a stale
// entry that is USED is far worse than one that is missed, because it produces
// a hull whose damage volume silently does not match its geometry.
//
// No real hull assets: the cache is exercised through a synthetic .nif-free
// path by baking from triangles directly, plus disk-level checks on the
// resulting file.
#include <gtest/gtest.h>

#include <voxel/hull_volume_cache.h>
#include <voxel/dhv.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <system_error>
#include <thread>

namespace {

// Unique per PROCESS (not per test): this checkout is shared by concurrent
// Claude sessions, and two `ctest` runs sharing one fixed /tmp path would
// collide on each other's cache files. A thread-id hash plus a
// steady_clock reading, latched once via a function-local static, gives
// every process invocation of this test binary its own scratch directory
// without pulling in a platform-specific getpid().
std::filesystem::path scratch_root() {
    static const std::filesystem::path root = [] {
        std::ostringstream os;
        os << "dauntless_hvcache_test_"
           << std::hash<std::thread::id>{}(std::this_thread::get_id()) << '_'
           << std::chrono::steady_clock::now().time_since_epoch().count();
        return std::filesystem::temp_directory_path() / os.str();
    }();
    return root;
}

void clear_scratch() {
    std::error_code ec;
    std::filesystem::remove_all(scratch_root(), ec);
}

// RAII cleanup: a failing ASSERT_* returns out of the TEST() function
// early, which skips any cleanup written as a plain statement at the end of
// the test body. A local destructor still runs on that early return, so
// this makes cleanup unconditional -- debris is not left behind for a
// failing assertion the way clear_scratch() called only at a test's tail
// would leave it.
struct ScratchGuard {
    ~ScratchGuard() { clear_scratch(); }
};

// A minimal file standing in for a hull source, so fingerprinting has
// something real to read. Baking from it yields an empty field (no triangles),
// which is fine: these tests are about keys, files and invalidation.
std::filesystem::path make_source(const char* name, const char* body) {
    const auto p = scratch_root() / name;
    std::filesystem::create_directories(scratch_root());
    std::ofstream s(p, std::ios::binary | std::ios::trunc);
    s << body;
    return p;
}

}  // namespace

TEST(HullVolumeCache, KeyChangesWithQualityAndResolution) {
    clear_scratch();
    ScratchGuard guard;
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    const auto a = c.path_for(src, 10.0f, 1.0f);
    const auto b = c.path_for(src, 10.0f, 2.0f);
    const auto d = c.path_for(src,  8.0f, 2.0f);

    EXPECT_NE(a, b) << "quality must be part of the key";
    EXPECT_NE(b, d) << "authored resolution must be part of the key";
    EXPECT_EQ(a.extension().string(), ".dhv");
}

TEST(HullVolumeCache, DistinctSourcesGetDistinctFiles) {
    clear_scratch();
    ScratchGuard guard;
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto s1 = make_source("hullA.nif", "hull-a");
    const auto s2 = make_source("hullB.nif", "hull-b-longer");
    EXPECT_NE(c.path_for(s1, 10.0f, 2.0f), c.path_for(s2, 10.0f, 2.0f));
}

TEST(HullVolumeCache, FirstGetWritesACacheFile) {
    clear_scratch();
    ScratchGuard guard;
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_TRUE(std::filesystem::exists(c.path_for(src, 10.0f, 2.0f)))
        << "a bake must be persisted, or every launch pays for it again";
}

TEST(HullVolumeCache, SecondGetReadsTheCacheRatherThanRebaking) {
    clear_scratch();
    ScratchGuard guard;
    const auto src = make_source("hullA.nif", "hull-a");
    const auto cache_root = scratch_root() / "cache";

    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
        EXPECT_EQ(warm.bakes(), 1u) << "a cold cache must bake exactly once";
    }

    voxel::HullVolumeCache cold(cache_root);   // fresh: no in-memory memo
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 0u)
        << "a valid cache file must be LOADED, not rebaked -- otherwise the "
           "cache is inert and every launch pays first-load cost again";
}

TEST(HullVolumeCache, ServesAWrittenFieldWithoutRebaking) {
    // The only test in this file that round-trips a REAL (non-empty)
    // payload through the cache's own composition: every other test's
    // synthetic source is not a NIF, so nif::load throws inside get() and
    // the baked field stays dims{0,0,0}. SecondGetReadsTheCacheRatherThan-
    // Rebaking proves bakes()==0 on a hit, but never that the served field
    // actually equals what was written -- this drives write_dhv directly
    // (bypassing the bake path entirely) with a real payload at the exact
    // location and metadata path_for/get expect, then asserts get() serves
    // it back field-for-field.
    clear_scratch();
    ScratchGuard guard;
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    const float authored_res = 10.0f;
    const float quality = 2.0f;

    voxel::DistanceField field;
    field.dims   = glm::ivec3(2, 3, 4);
    field.origin = glm::vec3(-1.0f, -2.0f, -3.0f);
    field.cell   = glm::vec3(5.0f, 5.0f, 5.0f);
    field.scale  = 0.25f;
    field.dist.resize(2 * 3 * 4);
    for (std::size_t i = 0; i < field.dist.size(); ++i)
        field.dist[i] = static_cast<std::int8_t>(static_cast<int>(i) - 10);

    // Mirror HullVolumeCache::get's own fingerprinting exactly, computed
    // from the same `src` file with no mutation in between, so the entry
    // this test writes validates as current rather than stale.
    voxel::HullVolumeMeta meta;
    meta.baker_version = voxel::kBakerVersion;
    {
        std::error_code ec;
        meta.source_size =
            static_cast<std::uint32_t>(std::filesystem::file_size(src, ec));
    }
    {
        std::error_code ec;
        const auto t = std::filesystem::last_write_time(src, ec);
        meta.source_mtime =
            static_cast<std::int64_t>(t.time_since_epoch().count());
    }
    meta.authored_res = authored_res;
    meta.quality       = quality;
    meta.source_path   = src.string();

    voxel::HullVolumeCache c(cache_root);
    const auto p = c.path_for(src, authored_res, quality);
    ASSERT_TRUE(voxel::write_dhv(p, field, meta));

    const voxel::DistanceField& served = c.get(src, authored_res, quality);
    EXPECT_EQ(c.bakes(), 0u)
        << "a pre-populated, valid cache file must be served, not rebaked";
    EXPECT_EQ(served.dims, field.dims);
    EXPECT_EQ(served.origin, field.origin);
    EXPECT_EQ(served.cell, field.cell);
    EXPECT_FLOAT_EQ(served.scale, field.scale);
    EXPECT_EQ(served.dist, field.dist);
}

TEST(HullVolumeCache, RepeatedGetUsesTheInMemoryMemo) {
    clear_scratch();
    ScratchGuard guard;
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    (void)c.get(src, 10.0f, 2.0f);
    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(c.bakes(), 1u);
}

TEST(HullVolumeCache, ChangedSourceInvalidatesTheEntry) {
    clear_scratch();
    ScratchGuard guard;
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
    }

    // Rewrite the source at a DIFFERENT LENGTH: the stored fingerprint no
    // longer matches, so the entry must not be served.
    make_source("hullA.nif", "hull-a-but-edited-and-rather-longer");

    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u)
        << "an edited hull must be rebaked; serving a stale volume gives a "
           "ship damage geometry that does not match its mesh";
}

TEST(HullVolumeCache, ChangedQualityInvalidatesTheEntry) {
    clear_scratch();
    ScratchGuard guard;
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 1.0f);
    }
    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u) << "quality is part of the key";
}

TEST(HullVolumeCache, CorruptCacheFileIsRebakedRatherThanTrusted) {
    clear_scratch();
    ScratchGuard guard;
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 2.0f);
    }
    const auto p = voxel::HullVolumeCache(cache_root).path_for(src, 10.0f, 2.0f);
    { std::ofstream s(p, std::ios::binary | std::ios::trunc); s << "junk"; }

    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u) << "junk must be rebaked, never half-trusted";

    voxel::DistanceField f;
    voxel::HullVolumeMeta m;
    EXPECT_TRUE(voxel::read_dhv(p, f, m))
        << "a corrupt entry must be REPLACED by a good one, not just ignored";
}

TEST(HullVolumeCache, RepeatedGetReturnsTheSameObject) {
    clear_scratch();
    ScratchGuard guard;
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    const voxel::DistanceField& a = c.get(src, 10.0f, 2.0f);
    const voxel::DistanceField& b = c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(&a, &b) << "references must stay stable for the cache's lifetime";
}

namespace {
// Raw clock ticks: EXPECT_EQ on a file_time_type drags gtest's printer into
// <format>, which this SDK's deployment target does not have.
long long mtime_ticks(const std::filesystem::path& p) {
    return static_cast<long long>(
        std::filesystem::last_write_time(p).time_since_epoch().count());
}
}  // namespace

// ── ensure_dhv: the bake-or-validate step on its own ───────────────────────
//
// The boot-time pre-bake runs this from a WORKER thread so a mission never
// pays a bake on the main thread. It must therefore be a free function that
// touches only the filesystem -- no HullVolumeCache memo, no shared map --
// and it must be exactly the step `get` performs, so a file it writes is
// one `get` accepts without rebaking.

TEST(EnsureDhv, WritesTheFileGetWouldWrite) {
    clear_scratch();
    ScratchGuard guard;
    const auto src = make_source("hullA.nif", "hull-a");
    const auto cache_root = scratch_root() / "cache";

    EXPECT_TRUE(voxel::ensure_dhv(cache_root, src, 10.0f, 2.0f));

    voxel::HullVolumeCache c(cache_root);
    EXPECT_TRUE(std::filesystem::exists(c.path_for(src, 10.0f, 2.0f)));
    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(c.bakes(), 0u)
        << "a file ensure_dhv wrote must satisfy get without a rebake -- "
           "otherwise the pre-bake is inert and spawn pays the bake anyway";
}

TEST(EnsureDhv, ValidFileIsLeftAloneNotRewritten) {
    clear_scratch();
    ScratchGuard guard;
    const auto src = make_source("hullA.nif", "hull-a");
    const auto cache_root = scratch_root() / "cache";
    ASSERT_TRUE(voxel::ensure_dhv(cache_root, src, 10.0f, 2.0f));

    voxel::HullVolumeCache c(cache_root);
    const auto file = c.path_for(src, 10.0f, 2.0f);
    const auto before = mtime_ticks(file);
    // Coarse-mtime filesystems: make sure a rewrite WOULD be observable.
    std::this_thread::sleep_for(std::chrono::milliseconds(20));

    EXPECT_TRUE(voxel::ensure_dhv(cache_root, src, 10.0f, 2.0f));
    EXPECT_EQ(mtime_ticks(file), before)
        << "a valid entry must not be rebaked -- the pre-bake runs every "
           "boot, and rewriting the whole fleet each time defeats the cache";
}

TEST(EnsureDhv, StaleFileIsRebaked) {
    clear_scratch();
    ScratchGuard guard;
    auto src = make_source("hullA.nif", "hull-a");
    const auto cache_root = scratch_root() / "cache";
    ASSERT_TRUE(voxel::ensure_dhv(cache_root, src, 10.0f, 2.0f));

    voxel::HullVolumeCache c(cache_root);
    const auto file = c.path_for(src, 10.0f, 2.0f);
    const auto before = mtime_ticks(file);
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    src = make_source("hullA.nif", "hull-a-edited!");   // size changes

    EXPECT_TRUE(voxel::ensure_dhv(cache_root, src, 10.0f, 2.0f));
    EXPECT_NE(mtime_ticks(file), before)
        << "a fingerprint mismatch must rebake, exactly as get does";
}

TEST(EnsureDhv, MissingSourceReportsFalse) {
    clear_scratch();
    ScratchGuard guard;
    const auto cache_root = scratch_root() / "cache";
    EXPECT_FALSE(voxel::ensure_dhv(cache_root,
                                   scratch_root() / "nope.nif", 10.0f, 2.0f))
        << "nothing to bake from: the worker must be able to count this "
           "as a skip rather than a success";
}
