// native/tests/renderer/minor_field_test.cc
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <renderer/minor_field.h>

#include <cmath>

#include <glm/gtc/matrix_transform.hpp>

using namespace renderer::minors;

namespace {
CloudDesc halo(std::uint32_t seed = 7) {
    CloudDesc d;
    d.id = 1; d.anchor = Anchor::Point; d.seed = seed;
    d.shell_inner = 1.1f * 4.0f; d.shell_outer = 3.0f * 4.0f; d.falloff = 1.0f;
    d.count = 200; d.r_min = 0.03f; d.r_max = 0.6f; d.size_exponent = 2.5f;
    return d;
}
}  // namespace

TEST(MinorGenerate, DeterministicPerSeed) {
    auto a = generate(halo(7)), b = generate(halo(7)), c = generate(halo(8));
    ASSERT_EQ(a.size(), 200u);
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].offset, b[i].offset);
        EXPECT_EQ(a[i].radius, b[i].radius);
        EXPECT_EQ(a[i].mesh_u, b[i].mesh_u);
    }
    EXPECT_NE(a[0].offset, c[0].offset);
}

TEST(MinorGenerate, InsideShellAndRadiusRange) {
    const auto d = halo();
    for (const auto& m : generate(d)) {
        const float r = glm::length(m.offset);
        EXPECT_GE(r, d.shell_inner - 1e-4f);
        EXPECT_LE(r, d.shell_outer + 1e-4f);
        EXPECT_GE(m.radius, d.r_min - 1e-6f);
        EXPECT_LE(m.radius, d.r_max + 1e-6f);
        EXPECT_NEAR(glm::length(m.tumble_axis), 1.0f, 1e-4f);
        EXPECT_GE(m.orbit_u, 0.5f); EXPECT_LE(m.orbit_u, 1.0f);
    }
}

TEST(MinorGenerate, FalloffPullsMinorsInward) {
    auto d0 = halo(); d0.falloff = 0.0f; d0.count = 4000;
    auto d1 = halo(); d1.falloff = 2.0f; d1.count = 4000;
    double m0 = 0, m1 = 0;
    for (const auto& m : generate(d0)) m0 += glm::length(m.offset);
    for (const auto& m : generate(d1)) m1 += glm::length(m.offset);
    EXPECT_LT(m1 / 4000.0, m0 / 4000.0 - 0.3);
}

TEST(MinorGenerate, PowerLawFavoursSmallRadii) {
    auto d = halo(); d.count = 4000;
    int small = 0;
    const float mid = 0.5f * (d.r_min + d.r_max);
    for (const auto& m : generate(d)) small += m.radius < mid ? 1 : 0;
    EXPECT_GT(small, 3000);    // well over half below the midpoint
}

TEST(MinorGenerate, UniformSphereWhenInnerZeroAndNoFalloff) {
    CloudDesc d; d.seed = 3; d.shell_inner = 0; d.shell_outer = 100;
    d.count = 8000; d.r_min = 0.05f; d.r_max = 0.7f;
    int inner_half = 0;        // r < R/2 holds 1/8 of a uniform sphere
    for (const auto& m : generate(d)) inner_half += glm::length(m.offset) < 50 ? 1 : 0;
    EXPECT_NEAR(inner_half / 8000.0, 0.125, 0.02);
}

TEST(MinorGenerate, DebrisAppendedVerbatim) {
    CloudDesc d; d.anchor = Anchor::Free; d.count = 10;
    d.debris = {{{1, 0, 0}, {0.8f, 0, 0}, 0.4f, 11}, {{0, 1, 0}, {0, 0.8f, 0}, 0.2f, 12}};
    auto g = generate(d);
    ASSERT_EQ(g.size(), 12u);
    EXPECT_TRUE(g[10].debris);
    EXPECT_EQ(g[10].offset, glm::vec3(1, 0, 0));
    EXPECT_EQ(g[10].v0, glm::vec3(0.8f, 0, 0));
    EXPECT_FLOAT_EQ(g[11].radius, 0.2f);
}

TEST(MinorGenerate, ZeroCountIsEmpty) {
    CloudDesc d; d.count = 0;
    EXPECT_TRUE(generate(d).empty());
}

namespace {
StepInput looking_down_minus_z(double t = 0.0) {
    StepInput in;
    in.game_time = t;
    in.view = glm::lookAt(glm::vec3(0, 0, 0), glm::vec3(0, 0, -1), glm::vec3(0, 1, 0));
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1e6f);
    in.viewport_h = 1080.0f;
    return in;
}
MinorField field_with_fragments() {
    MinorField f;
    f.set_fragments(0, {Fragment{1, 2, 57.142857f}, Fragment{3, 4, 57.142857f}});
    return f;
}
CloudDesc point_cloud(glm::dvec3 at, int count = 50) {
    CloudDesc d; d.id = 9; d.anchor = Anchor::Point; d.point = at;
    d.shell_inner = 0; d.shell_outer = 2; d.count = count;
    d.r_min = 0.3f; d.r_max = 0.3f; d.seed = 1;
    return d;
}
}  // namespace

TEST(MinorStep, PointCloudInViewIsDrawnAndBinned) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.step(looking_down_minus_z());
    const auto s = f.stats();
    EXPECT_EQ(s.clouds, 1); EXPECT_EQ(s.minors, 50); EXPECT_EQ(s.drawn, 50);
    EXPECT_GE(s.bins, 1); EXPECT_LE(s.bins, 4);     // 2 slots x 2 lods
}

TEST(MinorStep, BehindCameraIsCulled) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, +20}), 0.0);
    f.step(looking_down_minus_z());
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, SubPixelIsCulledAndLodSwitchesWithDistance) {
    // pixel_r = r * proj[1][1] * 0.5 * viewport_h / depth, proj[1][1] = 1/tan(30deg) = 1.732
    // 0.3 GU at 5 GU    -> ~56 px  (lod0)
    // 0.3 GU at 100 GU  -> ~2.8 px (lod1)
    // 0.3 GU at 50k GU  -> ~0.006 px (culled)
    auto f = field_with_fragments();
    auto near = point_cloud({0, 0, -5}); near.id = 1;
    auto far = point_cloud({0, 0, -100}); far.id = 2;
    auto gone = point_cloud({0, 0, -50000}); gone.id = 3;
    f.add_cloud(near, 0); f.add_cloud(far, 0); f.add_cloud(gone, 0);
    f.step(looking_down_minus_z());
    int lod0 = 0, lod1 = 0;
    for (const auto& b : f.bins()) (b.lod == 0 ? lod0 : lod1) += int(b.items.size());
    EXPECT_EQ(lod0, 50);
    EXPECT_EQ(lod1, 50);
    EXPECT_EQ(f.stats().drawn, 100);
}

TEST(MinorStep, RenderOriginIsSubtractedForPointAnchors) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({1000, 0, -20}), 0.0);
    auto in = looking_down_minus_z();
    in.render_origin = glm::dvec3(1000, 0, 0);
    f.step(in);
    EXPECT_EQ(f.stats().drawn, 50);
}

TEST(MinorStep, InstanceAnchorFollowsLookupByTranslationOnly) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, 0}); d.anchor = Anchor::Instance; d.instance_key = 42;
    f.add_cloud(d, 0.0);
    glm::vec3 where(0, 0, -20);
    auto in = looking_down_minus_z();
    in.anchor_of = [&](std::uint64_t k, glm::vec3& out) { if (k != 42) return false; out = where; return true; };
    f.step(in);
    glm::vec3 p0; ASSERT_TRUE(f.minor_position(9, 0, p0));
    where = glm::vec3(5, 0, -20);
    f.step(in);
    glm::vec3 p1; ASSERT_TRUE(f.minor_position(9, 0, p1));
    EXPECT_NEAR(p1.x - p0.x, 5.0f, 1e-4f);
}

TEST(MinorStep, MissingInstanceAnchorDrawsNothing) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.anchor = Anchor::Instance; d.instance_key = 1;
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z();
    in.anchor_of = [](std::uint64_t, glm::vec3&) { return false; };
    f.step(in);
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, FreeCloudMovesAnalytically) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.anchor = Anchor::Free;
    d.velocity = glm::vec3(1, 0, 0); d.t0 = 10.0;
    f.add_cloud(d, 10.0);
    f.step(looking_down_minus_z(10.0));
    glm::vec3 a; f.minor_position(9, 0, a);
    f.step(looking_down_minus_z(13.0));
    glm::vec3 b; f.minor_position(9, 0, b);
    EXPECT_NEAR(b.x - a.x, 3.0f, 1e-3f);
}

TEST(MinorStep, DebrisDecaysToAFiniteSpread) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}, 0); d.anchor = Anchor::Free; d.t0 = 0.0;
    d.debris = {{{0, 0, 0}, {1, 0, 0}, 0.3f, 5}};
    f.add_cloud(d, 0.0);
    const float tau = 6.0f / std::log(2.0f);
    f.step(looking_down_minus_z(1000.0));
    glm::vec3 p; f.minor_position(9, 0, p);
    EXPECT_NEAR(p.x, tau, 1e-2f);                  // v0·τ at t → ∞
    // Matches a fine step-by-step integration of v = v0·0.5^(t/h):
    double x = 0, v = 1, dt = 1e-3;
    for (int i = 0; i < 6000; ++i) { x += v * dt; v *= std::pow(0.5, dt / 6.0); }
    f.step(looking_down_minus_z(6.0));
    f.minor_position(9, 0, p);
    EXPECT_NEAR(p.x, float(x), 2e-3f);
}

TEST(MinorStep, OrbitKeepsDistanceFromAnchor) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.orbit_rate = 0.5f;
    f.add_cloud(d, 0.0);
    f.step(looking_down_minus_z(0.0));
    glm::vec3 a; f.minor_position(9, 3, a);
    f.step(looking_down_minus_z(7.0));
    glm::vec3 b; f.minor_position(9, 3, b);
    const glm::vec3 c(0, 0, -20);
    EXPECT_NEAR(glm::length(a - c), glm::length(b - c), 1e-3f);
    EXPECT_GT(glm::length(a - b), 1e-3f);
}

TEST(MinorStep, FadeInScalesFromZero) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, -20}); d.fade_in = true;
    f.add_cloud(d, 5.0);
    f.step(looking_down_minus_z(5.0));
    EXPECT_EQ(f.stats().drawn, 0);                 // scale 0 at birth
    f.step(looking_down_minus_z(5.0 + 1.5));
    EXPECT_EQ(f.stats().drawn, 50);
}

TEST(MinorStep, FadeOutReachesZero) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.fade_out(9, 2.0f, 1.0);
    f.step(looking_down_minus_z(3.5));
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, DetachKeepsMinorsAndTurnsFree) {
    auto f = field_with_fragments();
    CloudDesc d = point_cloud({0, 0, 0}); d.anchor = Anchor::Instance; d.instance_key = 7;
    f.add_cloud(d, 0.0);
    auto in = looking_down_minus_z(0.0);
    in.anchor_of = [](std::uint64_t, glm::vec3& o) { o = {0, 0, -20}; return true; };
    f.step(in);
    glm::vec3 before; f.minor_position(9, 0, before);
    f.detach(9, glm::dvec3(0, 0, -20), glm::vec3(0), 0.0, {{{0, 0, 0}, {0, 0, 0}, 0.2f, 1}});
    in.anchor_of = nullptr;                        // rock gone
    f.step(in);
    glm::vec3 after; ASSERT_TRUE(f.minor_position(9, 0, after));
    EXPECT_NEAR(glm::length(after - before), 0.0f, 1e-4f);
    EXPECT_EQ(f.stats().minors, 51);
}

TEST(MinorStep, NoFragmentsDrawsNothing) {
    MinorField f;
    f.add_cloud(point_cloud({0, 0, -20}), 0.0);
    f.step(looking_down_minus_z());
    EXPECT_EQ(f.stats().drawn, 0);
}

TEST(MinorStep, InstanceScaleDrawsAtMinorRadius) {
    auto f = field_with_fragments();
    f.add_cloud(point_cloud({0, 0, -20}, 1), 0.0);
    f.step(looking_down_minus_z());
    ASSERT_FALSE(f.bins().empty());
    const auto& g = f.bins()[0].items[0];
    const float s = glm::length(glm::vec3(g.row0.x, g.row1.x, g.row2.x));
    EXPECT_NEAR(s * 57.142857f * 0.01f, 0.3f, 1e-4f);
}
