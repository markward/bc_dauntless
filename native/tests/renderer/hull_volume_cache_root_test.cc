// renderer::set_hull_volume_cache_root / renderer::hull_volume_cache().
//
// Task 3 of the hull-volume field transport plan: nothing had ever
// constructed a voxel::HullVolumeCache before this, so its root had never
// actually been resolved. This proves the plumbing, not the baker itself
// (voxel/tests/hull_volume_cache_test.cc already covers baking/loading).
//
// IMPORTANT: hull_volume_cache() is a process-wide lazy singleton --
// "constructed on first use with the configured root" per its header comment
// -- so only the FIRST call anywhere in this test binary observes whatever
// root was configured beforehand; every later call, from any test, gets the
// same already-built instance regardless of what set_hull_volume_cache_root
// is told afterward. This file exists to be the ONLY caller of either
// function in the whole renderer_tests binary, in exactly one TEST, so that
// "first call" is deterministic. Do not add a second TEST() here (or a call
// to either function from any other test file) -- it would make whichever
// TEST happens to run first win, silently, and the loser would look like a
// broken feature instead of a mis-ordered fixture.
#include <gtest/gtest.h>

#include <renderer/carve_field_cache.h>

TEST(HullVolumeCacheRoot, SingletonPicksUpTheRootConfiguredBeforeFirstUse) {
    const std::filesystem::path root = "/tmp/dauntless_test_hull_volume_root";
    renderer::set_hull_volume_cache_root(root);

    voxel::HullVolumeCache& cache = renderer::hull_volume_cache();

    // path_for() is pure string/hash math (voxel/src/hull_volume_cache.cc) --
    // no disk I/O -- so this proves the singleton was actually constructed
    // with `root`, not with the temp-directory fallback, without needing a
    // real hull asset to bake against.
    const std::filesystem::path entry =
        cache.path_for("some/hull.nif", 10.0f, voxel::kDefaultQuality);
    EXPECT_EQ(entry.parent_path(), root);

    // Referencing the same singleton twice must not construct it twice (and
    // must not crash) -- get() on an empty/missing hull path returns an
    // empty field rather than throwing.
    EXPECT_EQ(&cache, &renderer::hull_volume_cache());
}
