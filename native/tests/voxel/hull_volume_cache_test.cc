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

#include <filesystem>
#include <fstream>

namespace {

std::filesystem::path scratch_root() {
    return std::filesystem::temp_directory_path() / "dauntless_hvcache_test";
}

void clear_scratch() {
    std::error_code ec;
    std::filesystem::remove_all(scratch_root(), ec);
}

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
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    const auto a = c.path_for(src, 10.0f, 1.0f);
    const auto b = c.path_for(src, 10.0f, 2.0f);
    const auto d = c.path_for(src,  8.0f, 2.0f);

    EXPECT_NE(a, b) << "quality must be part of the key";
    EXPECT_NE(b, d) << "authored resolution must be part of the key";
    EXPECT_EQ(a.extension().string(), ".dhv");
    clear_scratch();
}

TEST(HullVolumeCache, DistinctSourcesGetDistinctFiles) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto s1 = make_source("hullA.nif", "hull-a");
    const auto s2 = make_source("hullB.nif", "hull-b-longer");
    EXPECT_NE(c.path_for(s1, 10.0f, 2.0f), c.path_for(s2, 10.0f, 2.0f));
    clear_scratch();
}

TEST(HullVolumeCache, FirstGetWritesACacheFile) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");

    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_TRUE(std::filesystem::exists(c.path_for(src, 10.0f, 2.0f)))
        << "a bake must be persisted, or every launch pays for it again";
    clear_scratch();
}

TEST(HullVolumeCache, SecondGetReadsTheCacheRatherThanRebaking) {
    clear_scratch();
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
    clear_scratch();
}

TEST(HullVolumeCache, RepeatedGetUsesTheInMemoryMemo) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    (void)c.get(src, 10.0f, 2.0f);
    (void)c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(c.bakes(), 1u);
    clear_scratch();
}

TEST(HullVolumeCache, ChangedSourceInvalidatesTheEntry) {
    clear_scratch();
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
    clear_scratch();
}

TEST(HullVolumeCache, ChangedQualityInvalidatesTheEntry) {
    clear_scratch();
    const auto cache_root = scratch_root() / "cache";
    const auto src = make_source("hullA.nif", "hull-a");
    {
        voxel::HullVolumeCache warm(cache_root);
        (void)warm.get(src, 10.0f, 1.0f);
    }
    voxel::HullVolumeCache cold(cache_root);
    (void)cold.get(src, 10.0f, 2.0f);
    EXPECT_EQ(cold.bakes(), 1u) << "quality is part of the key";
    clear_scratch();
}

TEST(HullVolumeCache, CorruptCacheFileIsRebakedRatherThanTrusted) {
    clear_scratch();
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
    clear_scratch();
}

TEST(HullVolumeCache, RepeatedGetReturnsTheSameObject) {
    clear_scratch();
    voxel::HullVolumeCache c(scratch_root() / "cache");
    const auto src = make_source("hullA.nif", "hull-a");
    const voxel::DistanceField& a = c.get(src, 10.0f, 2.0f);
    const voxel::DistanceField& b = c.get(src, 10.0f, 2.0f);
    EXPECT_EQ(&a, &b) << "references must stay stable for the cache's lifetime";
    clear_scratch();
}
