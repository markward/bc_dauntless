// native/tests/renderer/minor_field_test.cc
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <renderer/minor_field.h>

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
