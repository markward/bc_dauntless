// native/tests/renderer/bridge_light_cull_test.cc
//
// Per-draw light culling for the bridge pass (perf-register SIG-134,
// SIG-138): a light may be skipped for a mesh only when bridge.frag's own
// per-fragment tests would give it exactly zero at every point of the mesh's
// world box. The property tests sample boxes against the CPU twin's tests.
#include <gtest/gtest.h>
#include <renderer/bridge_light_cull.h>
#include <renderer/bridge_pbr.h>

#include <glm/gtc/matrix_transform.hpp>

#include <random>

using namespace renderer;

namespace {

// The shader's area-light early-outs for one fragment: true = lit at all.
bool area_lights_point(glm::vec3 p, glm::vec3 c, glm::vec3 u, glm::vec3 v, float range) {
    const glm::vec3 uv = glm::cross(u, v);
    if (glm::dot(uv, uv) < 1e-12f) return false;
    if (glm::dot(glm::normalize(uv), p - c) <= 0.0f) return false;
    const float dn = glm::length(pbr::rect_nearest(p, c, u, v) - p);
    return pbr::range_window(dn, range) > 0.0f;
}

glm::vec3 lerp3(glm::vec3 a, glm::vec3 b, glm::vec3 t) { return a + (b - a) * t; }

}  // namespace

TEST(BridgeLightCull, AreaLightBehindTheWholeBoxIsSkipped) {
    // Emits +z from z = 10; a box wholly below it is behind the light.
    const glm::vec3 c(0, 0, 10), u(2, 0, 0), v(0, 1, 0);
    EXPECT_FALSE(bridge_cull::area_can_reach({-5, -5, 0}, {5, 5, 9}, c, u, v, 300.0f));
    // A box straddling the plane is not.
    EXPECT_TRUE(bridge_cull::area_can_reach({-5, -5, 0}, {5, 5, 11}, c, u, v, 300.0f));
}

TEST(BridgeLightCull, AreaLightOutOfRangeIsSkipped) {
    const glm::vec3 c(0, 0, 0), u(2, 0, 0), v(0, 1, 0);   // emits +z
    EXPECT_FALSE(bridge_cull::area_can_reach({-1, -1, 150}, {1, 1, 160}, c, u, v, 120.0f));
    EXPECT_TRUE(bridge_cull::area_can_reach({-1, -1, 100}, {1, 1, 160}, c, u, v, 120.0f));
}

TEST(BridgeLightCull, ZeroAreaLightIsSkipped) {
    EXPECT_FALSE(bridge_cull::area_can_reach({-1, -1, 1}, {1, 1, 2}, {0, 0, 0},
                                             {2, 0, 0}, {0, 0, 0}, 120.0f));
}

TEST(BridgeLightCull, SpotOutOfRangeIsSkipped) {
    EXPECT_FALSE(bridge_cull::spot_can_reach({200, 0, 0}, {210, 5, 5}, {0, 0, 0}, 150.0f));
    EXPECT_TRUE(bridge_cull::spot_can_reach({100, 0, 0}, {210, 5, 5}, {0, 0, 0}, 150.0f));
    EXPECT_TRUE(bridge_cull::spot_can_reach({-5, -5, -5}, {5, 5, 5}, {0, 0, 0}, 150.0f));
}

TEST(BridgeLightCull, TransformedBoxContainsEveryTransformedCorner) {
    const glm::mat4 m = glm::rotate(glm::translate(glm::mat4(1.0f), glm::vec3(3, -2, 7)),
                                    0.7f, glm::normalize(glm::vec3(1, 2, 3)));
    const glm::vec3 lo(-1, -2, -3), hi(4, 5, 6);
    glm::vec3 wlo, whi;
    bridge_cull::transform_box(m, lo, hi, wlo, whi);
    for (int i = 0; i < 8; ++i) {
        const glm::vec3 k((i & 1) ? hi.x : lo.x, (i & 2) ? hi.y : lo.y, (i & 4) ? hi.z : lo.z);
        const glm::vec3 p = glm::vec3(m * glm::vec4(k, 1.0f));
        for (int a = 0; a < 3; ++a) {
            EXPECT_LE(wlo[a], p[a] + 1e-4f);
            EXPECT_GE(whi[a], p[a] - 1e-4f);
        }
    }
}

// The guarantee: a skipped light lights no point of the box.
TEST(BridgeLightCull, SkippedLightsLightNoPointOfTheBox) {
    std::mt19937 rng(7);
    std::uniform_real_distribution<float> pos(-300.0f, 300.0f), ext(0.5f, 60.0f),
        dir(-1.0f, 1.0f), unit(0.0f, 1.0f), rng_range(20.0f, 300.0f);
    int skipped_area = 0, skipped_spot = 0;
    for (int trial = 0; trial < 3000; ++trial) {
        const glm::vec3 lo(pos(rng), pos(rng), pos(rng));
        const glm::vec3 hi = lo + glm::vec3(ext(rng), ext(rng), ext(rng));
        const glm::vec3 c(pos(rng), pos(rng), pos(rng));
        const glm::vec3 a = glm::normalize(glm::vec3(dir(rng), dir(rng), dir(rng)));
        const glm::vec3 b = glm::normalize(glm::cross(a, glm::vec3(dir(rng), dir(rng), dir(rng))));
        const glm::vec3 u = a * ext(rng), v = b * ext(rng);
        const float range = rng_range(rng);
        if (!bridge_cull::area_can_reach(lo, hi, c, u, v, range)) {
            ++skipped_area;
            for (int s = 0; s < 200; ++s) {
                const glm::vec3 p = lerp3(lo, hi, {unit(rng), unit(rng), unit(rng)});
                ASSERT_FALSE(area_lights_point(p, c, u, v, range)) << "trial " << trial;
            }
        }
        if (!bridge_cull::spot_can_reach(lo, hi, c, range)) {
            ++skipped_spot;
            for (int s = 0; s < 200; ++s) {
                const glm::vec3 p = lerp3(lo, hi, {unit(rng), unit(rng), unit(rng)});
                ASSERT_EQ(pbr::spot_falloff(glm::length(c - p), range), 0.0f) << "trial " << trial;
            }
        }
    }
    // The property is only worth something if culling actually happens.
    EXPECT_GT(skipped_area, 300);
    EXPECT_GT(skipped_spot, 300);
}
