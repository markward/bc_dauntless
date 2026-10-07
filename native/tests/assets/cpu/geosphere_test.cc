// native/tests/assets/cpu/geosphere_test.cc
#include <assets/geosphere.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/constants.hpp>

#include <cmath>
#include <filesystem>
#include <variant>

#include <nif/block.h>
#include <nif/file.h>

#include "support/content_root.h"

namespace fs = std::filesystem;

TEST(Geosphere, TriangleCountPerLevel) {
    for (int level = 0; level <= 6; ++level) {
        const auto m = assets::build_geosphere(level, 1.0f);
        EXPECT_EQ(m.indices.size() / 3, 20u * (1u << (2 * level))) << "level " << level;
    }
}

TEST(Geosphere, EveryVertexOnTheRadiusAroundTheCenter) {
    const glm::vec3 c(-0.736648f, 0.368324f, 0.0f);
    const auto m = assets::build_geosphere(4, 90.0099f, c);
    for (const auto& v : m.vertices) {
        EXPECT_NEAR(glm::length(v.position - c), 90.0099f, 1e-3f);
        EXPECT_NEAR(glm::length(v.normal), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(v.normal, glm::normalize(v.position - c)), 1.0f, 1e-5f);
    }
}

TEST(Geosphere, EveryTriangleWindsCcwOutward) {
    const auto m = assets::build_geosphere(3, 1.0f);
    for (std::size_t i = 0; i < m.indices.size(); i += 3) {
        const glm::vec3 a = m.vertices[m.indices[i]].position;
        const glm::vec3 b = m.vertices[m.indices[i + 1]].position;
        const glm::vec3 c = m.vertices[m.indices[i + 2]].position;
        EXPECT_GT(glm::dot(glm::cross(b - a, c - a), a + b + c), 0.0f) << "tri " << i / 3;
    }
}

TEST(Geosphere, VertexUvIsTheSphereUvOfItsDirection) {
    const auto m = assets::build_geosphere(2, 5.0f);
    for (const auto& v : m.vertices) {
        const glm::vec2 want = assets::sphere_uv(glm::normalize(v.position));
        EXPECT_NEAR(v.uv.x, want.x, 1e-6f);
        EXPECT_NEAR(v.uv.y, want.y, 1e-6f);
    }
}

TEST(SphereUv, MatchesTheMeasuredFormulaAtCardinalPoints) {
    // u = fract(atan2(y,x)/2pi + 0.75), v = 0.5 - asin(z)/pi
    auto uv = assets::sphere_uv({1, 0, 0});  EXPECT_NEAR(uv.x, 0.75f, 1e-6f); EXPECT_NEAR(uv.y, 0.5f, 1e-6f);
    uv = assets::sphere_uv({0, -1, 0});      EXPECT_NEAR(uv.x, 0.50f, 1e-6f);
    uv = assets::sphere_uv({-1, 0, 0});      EXPECT_NEAR(uv.x, 0.25f, 1e-6f);
    uv = assets::sphere_uv({0, 0, 1});       EXPECT_NEAR(uv.y, 0.0f, 1e-6f);
    uv = assets::sphere_uv({0, 0, -1});      EXPECT_NEAR(uv.y, 1.0f, 1e-6f);
}

TEST(SphereUv, PoleIsFinite) {
    const glm::vec2 uv = assets::sphere_uv({0, 0, 1});
    EXPECT_TRUE(std::isfinite(uv.x));
    EXPECT_TRUE(std::isfinite(uv.y));
}

TEST(SphereUv, MatchesBcPlanetNifUvs) {
    const fs::path nif = test_support::game_root() / "data/Models/Environment/IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    nif::File f = nif::load(nif);
    int checked = 0;
    for (const auto& b : f.blocks) {
        const auto* d = std::get_if<nif::NiTriShapeData>(&b);
        if (!d) continue;
        ASSERT_FALSE(d->uv_sets.empty());
        for (std::size_t i = 0; i < d->vertices.size(); ++i) {
            const glm::vec3 p(d->vertices[i].x, d->vertices[i].y, d->vertices[i].z);
            const glm::vec3 dir = glm::normalize(p);
            const float bu = d->uv_sets[0][i].u, bv = d->uv_sets[0][i].v;
            // Skip the seam column (BC stores both u=0 and u=1 there) and the
            // pole rings (BC's pole fan stores out-of-range u).
            if (std::abs(dir.z) > 0.98f) continue;
            if (bu < 1e-3f || bu > 1.0f - 1e-3f) continue;
            const glm::vec2 uv = assets::sphere_uv(dir);
            EXPECT_NEAR(uv.x, bu, 1e-4f) << "vertex " << i;
            EXPECT_NEAR(uv.y, bv, 1e-4f) << "vertex " << i;
            ++checked;
        }
    }
    EXPECT_GT(checked, 500);
}

TEST(GeospherePick, OrbitAt150GuOnA3600PlanetPicksLevel5) {
    // d = R + 150; silhouette distance sqrt(d^2 - R^2) = 1050; focal 935 px.
    // Level 4 error ~1.92 px, level 5 ~0.48 px -> index 2 (level 5).
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 3750.0f, 935.0f), 2);
}

TEST(GeospherePick, FarAwayPicksTheCoarsestLevel) {
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 1.0e6f, 935.0f), 0);
}

TEST(GeospherePick, InsideOrOnTheSpherePicksTheFinestLevel) {
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 3600.0f, 935.0f), 3);
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 100.0f, 935.0f), 3);
}

TEST(GeospherePick, NeverGetsCoarserAsTheCameraApproaches) {
    int prev = 0;
    for (float d = 2.0e5f; d > 3601.0f; d *= 0.9f) {
        const int lvl = assets::pick_geosphere_level(3600.0f, d, 935.0f);
        EXPECT_GE(lvl, prev) << "d=" << d;
        prev = lvl;
    }
}
