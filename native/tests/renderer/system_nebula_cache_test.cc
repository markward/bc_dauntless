// native/tests/renderer/system_nebula_cache_test.cc
//
// The system-nebula far-field table cache (system_nebula_cache.h). The real
// build_profile costs ~7 s in a Debug build, so every test but
// BuildProfileMatchesTodaysUpload injects a counting fake Builder that
// returns a tiny BuiltProfile tagged with the profile's k_sys -- enough to
// tell which key's table came back without paying for a real one.
#include <gtest/gtest.h>

#include <renderer/nebula_atmosphere.h>
#include <renderer/system_nebula_cache.h>

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <thread>

namespace {

namespace atm = renderer::atmosphere;

atm::RadialProfile two_row_profile(float k_sys = 2.0e-5f) {
    atm::RadialProfile p;
    p.r = {0.0f, 120000.0f};
    p.nebula = {0.2f, 1.0f};
    p.k_sys = k_sys;
    p.star_radius = 2000.0f;
    p.cloud_rgb = glm::vec3(0.6f, 0.35f, 0.7f);
    p.star_rgb = glm::vec3(1.0f);
    return p;
}

/// A tiny table whose single radial texel carries the profile's k_sys, so a
/// test can tell WHICH key a returned table was built for.
atm::BuiltProfile tagged(const atm::RadialProfile& p) {
    atm::BuiltProfile b;
    b.radial = {glm::vec2(p.k_sys, 0.0f)};
    b.tau = {glm::vec3(0.0f)};
    b.inscatter = {glm::vec3(0.0f)};
    return b;
}

/// Spin `ready` until true or 2 s pass.
bool wait_ready(atm::TableCache& cache, const atm::RadialProfile& p,
                const atm::LookParams& look) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (std::chrono::steady_clock::now() < deadline) {
        if (cache.ready(p, look)) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return false;
}

}  // namespace

TEST(SystemNebulaCache, SameInputsSameKey) {
    const atm::LookParams look;
    EXPECT_EQ(atm::profile_key(two_row_profile(), look),
              atm::profile_key(two_row_profile(), look));
}

TEST(SystemNebulaCache, ChangedGChangesKey) {
    atm::LookParams a;
    atm::LookParams b;
    b.g = a.g + 0.05f;
    EXPECT_NE(atm::profile_key(two_row_profile(), a),
              atm::profile_key(two_row_profile(), b));
}

TEST(SystemNebulaCache, ChangedRowChangesKey) {
    const atm::LookParams look;
    atm::RadialProfile changed = two_row_profile();
    changed.nebula[1] = 0.5f;
    EXPECT_NE(atm::profile_key(two_row_profile(), look),
              atm::profile_key(changed, look));
}

TEST(TableCache, GetBuildsOnceThenHits) {
    std::atomic<int> calls{0};
    atm::TableCache cache([&](const atm::RadialProfile& p, const atm::LookParams&) {
        ++calls;
        return tagged(p);
    });
    const atm::LookParams look;
    const auto first = cache.get(two_row_profile(), look);
    const auto second = cache.get(two_row_profile(), look);
    EXPECT_EQ(calls.load(), 1);
    EXPECT_EQ(first.get(), second.get());
    EXPECT_EQ(cache.size(), 1u);
}

TEST(TableCache, PrebuildThenGetDoesNotRebuild) {
    std::atomic<int> calls{0};
    atm::TableCache cache([&](const atm::RadialProfile& p, const atm::LookParams&) {
        ++calls;
        return tagged(p);
    });
    const atm::LookParams look;
    cache.prebuild(two_row_profile(), look);
    ASSERT_TRUE(wait_ready(cache, two_row_profile(), look));
    const auto built = cache.get(two_row_profile(), look);
    ASSERT_NE(built, nullptr);
    EXPECT_EQ(calls.load(), 1);
}

TEST(TableCache, PrebuildIsIdempotentWhilePending) {
    std::atomic<int> calls{0};
    std::promise<void> gate;
    std::shared_future<void> latch = gate.get_future().share();
    atm::TableCache cache([&](const atm::RadialProfile& p, const atm::LookParams&) {
        ++calls;
        latch.wait();
        return tagged(p);
    });
    const atm::LookParams look;
    cache.prebuild(two_row_profile(), look);
    cache.prebuild(two_row_profile(), look);
    gate.set_value();
    ASSERT_TRUE(wait_ready(cache, two_row_profile(), look));
    cache.prebuild(two_row_profile(), look);   // cached now: still a no-op
    cache.get(two_row_profile(), look);
    EXPECT_EQ(calls.load(), 1);
}

TEST(TableCache, GetWaitsOnPendingInsteadOfRebuilding) {
    std::atomic<int> calls{0};
    std::promise<void> gate;
    std::shared_future<void> latch = gate.get_future().share();
    atm::TableCache cache([&](const atm::RadialProfile& p, const atm::LookParams&) {
        ++calls;
        latch.wait();
        return tagged(p);
    });
    const atm::LookParams look;
    cache.prebuild(two_row_profile(), look);
    std::thread release([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        gate.set_value();
    });
    const auto built = cache.get(two_row_profile(), look);   // blocks until released
    release.join();
    ASSERT_NE(built, nullptr);
    EXPECT_EQ(calls.load(), 1);
    EXPECT_EQ(cache.size(), 1u);
}

TEST(TableCache, PendingOldKeyDoesNotReplaceNewInstall) {
    const atm::RadialProfile a = two_row_profile(1.0e-5f);
    const atm::RadialProfile b = two_row_profile(3.0e-5f);
    std::promise<void> gate;
    std::shared_future<void> latch = gate.get_future().share();
    atm::TableCache cache([&](const atm::RadialProfile& p, const atm::LookParams&) {
        if (p.k_sys == a.k_sys) latch.wait();   // A's build blocks on the latch
        return tagged(p);
    });
    const atm::LookParams look;
    cache.prebuild(a, look);
    EXPECT_FALSE(cache.ready(a, look));
    const auto got_b = cache.get(b, look);   // built synchronously meanwhile
    ASSERT_NE(got_b, nullptr);
    EXPECT_EQ(got_b->radial[0].x, b.k_sys);

    gate.set_value();
    ASSERT_TRUE(wait_ready(cache, a, look));
    EXPECT_EQ(cache.get(b, look)->radial[0].x, b.k_sys);
    EXPECT_EQ(cache.get(b, look).get(), got_b.get());
    EXPECT_EQ(cache.get(a, look)->radial[0].x, a.k_sys);
    EXPECT_EQ(cache.size(), 2u);
}

// The ONE test that pays for a real build (~7 s in Debug).
TEST(SystemNebulaCache, BuildProfileMatchesTodaysUpload) {
    const atm::BuiltProfile built = atm::build_profile(two_row_profile(), atm::LookParams{});
    EXPECT_EQ(built.radial.size(), static_cast<std::size_t>(atm::kRadialTexels));
    EXPECT_EQ(built.tau.size(), static_cast<std::size_t>(atm::kTableR * atm::kTableMu));
    EXPECT_EQ(built.inscatter.size(), static_cast<std::size_t>(atm::kTableR * atm::kTableMu));
}
