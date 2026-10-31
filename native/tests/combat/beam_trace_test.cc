// resolve_hit_point (beam_trace.h) with FAKE trace hooks: the marshalling
// and the three instance outcomes of map 8.3.6, exactly. The differential
// against the Python, through the renderer's real trace, runs from
// tests/host/test_native_beam_trace.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t ship(double x, double y, double z, double radius) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        const int64_t h = m.register_row(Kind::Object, i, g, 1);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_f(h, Field::o_radius, radius);
        m.set_f(h, Field::_scale, 1.0);
        return h;
    }
};

// One recorded trace call.
struct Call {
    float o[3];
    float d[3];
    float max_dist;
};

// A fake host: the instance {1, 1} is live at `t`, and its trace returns
// `hit` (or nothing); any other id is stale.
struct FakeHost {
    Vec3 t{0.0, 0.0, 0.0};
    std::optional<TraceHit> hit;
    std::vector<Call> calls;

    TraceHooks hooks() {
        TraceHooks h;
        h.translation = [this](InstanceId id) -> std::optional<Vec3> {
            if (id.index != 1 || id.generation != 1) return std::nullopt;
            return t;
        };
        h.trace = [this](InstanceId id, const float o[3], const float d[3],
                         float max_dist) -> std::optional<TraceHit> {
            calls.push_back({{o[0], o[1], o[2]}, {d[0], d[1], d[2]}, max_dist});
            if (id.index != 1 || id.generation != 1)
                throw StaleInstance("ray_trace_mesh: invalid InstanceId");
            return hit;
        };
        return h;
    }
};

constexpr InstanceId kLive{1, 1};
constexpr InstanceId kStale{1, 2};

}  // namespace

TEST(BeamTrace, NoDirectionIsTheFallbackAndNoTrace) {
    World w;
    FakeHost host;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {0.0, -20.0, 0.0}, std::nullopt, 30.0,
        {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(r.tier, ResolvedHit::Tier::Fallback);
    EXPECT_EQ(r.point, (Vec3{1.0, 2.0, 3.0}));
    EXPECT_FALSE(r.normal.has_value());
    EXPECT_TRUE(host.calls.empty());
}

TEST(BeamTrace, AbsentInstanceIsTheFallbackWithNoSphereTier) {
    World w;
    FakeHost host;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    // The ray enters the sphere, but with no instance Python never looks.
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, std::nullopt, {0.0, -20.0, 0.0},
        Vec3{0.0, 1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(r.tier, ResolvedHit::Tier::Fallback);
    EXPECT_TRUE(host.calls.empty());
}

TEST(BeamTrace, StaleInstanceThrowsIntoTheSphereTier) {
    World w;
    FakeHost host;
    host.hit = TraceHit{{0.0f, -5.0f, 0.0f}, {0.0f, -1.0f, 0.0f}, 15.0f};
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, kStale, {0.0, -20.0, 0.0},
        Vec3{0.0, 1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(r.tier, ResolvedHit::Tier::Sphere);
    EXPECT_EQ(r.point, (Vec3{0.0, -5.0, 0.0}));
    EXPECT_FALSE(r.normal.has_value());
    // host_io: a stale id still reaches the binding, with the ABSOLUTE origin.
    ASSERT_EQ(host.calls.size(), 1u);
    EXPECT_EQ(host.calls[0].o[1], -20.0f);
}

TEST(BeamTrace, LiveMissFallsToTheSphereTierAndItsOrigin) {
    World w;
    FakeHost host;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {0.0, -20.0, 0.0},
        Vec3{0.0, 1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(r.tier, ResolvedHit::Tier::Sphere);
    EXPECT_EQ(r.point, (Vec3{0.0, -5.0, 0.0}));
    // Inside the sphere: Python returns the origin OBJECT.
    const ResolvedHit in = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {0.0, -1.0, 0.0},
        Vec3{0.0, 1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(in.tier, ResolvedHit::Tier::Origin);
    EXPECT_EQ(in.point, (Vec3{0.0, -1.0, 0.0}));
    // Sphere missed too: the fallback.
    const ResolvedHit out = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {0.0, -20.0, 0.0},
        Vec3{0.0, -1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(out.tier, ResolvedHit::Tier::Fallback);
}

TEST(BeamTrace, AHitIsRelativeNarrowedAndAddedBackInDouble) {
    World w;
    FakeHost host;
    host.t = {1e6 + 0.3, -7.0, 0.1};
    host.hit = TraceHit{{-2.5f, 0.125f, 0.0f}, {-1.0f, 0.0f, 0.0f}, 8.0f};
    const int64_t ship = w.ship(1e6 + 0.3, -7.0, 0.1, 5.0);
    // 0.01 GU off the instance: float spacing out here is 1/16, so narrowing
    // first and subtracting after would send 0.0, not ~0.01.
    const Vec3 origin{1e6 + 0.3 + 0.01, -7.0, 0.1};
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, origin, Vec3{0.1, 0.2, 0.3}, 0.1,
        {0.0, 0.0, 0.0}, std::nullopt);
    ASSERT_EQ(r.tier, ResolvedHit::Tier::Mesh);
    ASSERT_EQ(host.calls.size(), 1u);
    // rel = origin - t in double, THEN narrowed.
    EXPECT_EQ(host.calls[0].o[0], static_cast<float>(origin[0] - host.t[0]));
    EXPECT_NE(host.calls[0].o[0], 0.0f);
    EXPECT_EQ(host.calls[0].o[2], static_cast<float>(0.1 - 0.1));
    EXPECT_EQ(host.calls[0].d[0], static_cast<float>(0.1));
    EXPECT_EQ(host.calls[0].max_dist, static_cast<float>(0.1));
    EXPECT_EQ(r.point[0], static_cast<double>(-2.5f) + (1e6 + 0.3));
    EXPECT_EQ(r.point[1], static_cast<double>(0.125f) + -7.0);
    ASSERT_TRUE(r.normal.has_value());
    EXPECT_EQ(*r.normal, (Vec3{-1.0, 0.0, 0.0}));
}

TEST(BeamTrace, TheViewShiftGoesInByPlusAndComesBackByMinusOne) {
    World w;
    FakeHost host;
    host.t = {100.0, 0.0, 0.0};
    host.hit = TraceHit{{-2.0f, 0.0f, 0.0f}, {-1.0f, 0.0f, 0.0f}, 8.0f};
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    const Vec3 off{100.0, 0.0, 0.0};
    const ResolvedHit r = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {-10.0, 0.0, 0.0},
        Vec3{1.0, 0.0, 0.0}, 20.0, {0.0, 0.0, 0.0}, off);
    ASSERT_EQ(r.tier, ResolvedHit::Tier::Mesh);
    EXPECT_EQ(host.calls[0].o[0], -10.0f);      // (-10 + 100) - 100
    EXPECT_EQ(r.point[0], -2.0);                // (-2 + 100) + -100
}

TEST(BeamTrace, AZeroOffsetIsNoShiftEvenSignedOrNan) {
    World w;
    FakeHost host;
    host.t = {-0.0, -0.0, -0.0};
    host.hit = TraceHit{{-0.0f, -0.0f, -0.0f}, {-1.0f, 0.0f, 0.0f}, 8.0f};
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    // (-0.0, 0.0, -0.0) == (0, 0, 0): no shift, so the hit's -0.0 + -0.0
    // survives as -0.0. A shift back would add -1.0 * -0.0 = +0.0 -> +0.0.
    const ResolvedHit z = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {-10.0, 0.0, 0.0},
        Vec3{1.0, 0.0, 0.0}, 20.0, {0.0, 0.0, 0.0}, Vec3{-0.0, 0.0, -0.0});
    ASSERT_EQ(z.tier, ResolvedHit::Tier::Mesh);
    EXPECT_TRUE(std::signbit(z.point[0]));
    EXPECT_TRUE(std::signbit(z.point[2]));
    // A NaN component is a real shift (NaN != 0.0): the point goes NaN.
    const ResolvedHit n = resolve_hit_point(
        w.m, host.hooks(), ship, kLive, {-10.0, 0.0, 0.0},
        Vec3{1.0, 0.0, 0.0}, 20.0, {0.0, 0.0, 0.0}, Vec3{kNan, 0.0, 0.0});
    ASSERT_EQ(n.tier, ResolvedHit::Tier::Mesh);
    EXPECT_TRUE(std::isnan(n.point[0]));
    EXPECT_TRUE(std::isnan(host.calls.back().o[0]));
}

TEST(BeamTrace, NoHooksIsAHeadlessMiss) {
    World w;
    const int64_t ship = w.ship(0.0, 0.0, 0.0, 5.0);
    const ResolvedHit r = resolve_hit_point(
        w.m, TraceHooks{}, ship, kLive, {0.0, -20.0, 0.0},
        Vec3{0.0, 1.0, 0.0}, 30.0, {1.0, 2.0, 3.0}, std::nullopt);
    EXPECT_EQ(r.tier, ResolvedHit::Tier::Sphere);
}

TEST(BeamTrace, NarrowingRoundsLikeACCast) {
    EXPECT_EQ(narrow_like_pybind(1e300), std::numeric_limits<float>::infinity());
    EXPECT_EQ(narrow_like_pybind(-1e300), -std::numeric_limits<float>::infinity());
    EXPECT_TRUE(std::isnan(narrow_like_pybind(kNan)));
    EXPECT_TRUE(std::signbit(narrow_like_pybind(-0.0)));
    // A tie rounds to even.
    EXPECT_EQ(narrow_like_pybind(1.0 + std::ldexp(1.0, -24)), 1.0f);
}
