#include <gtest/gtest.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>

#include "mini_recipe.h"

#include <glm/glm.hpp>
#include <glm/gtc/constants.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

namespace {

/// Number of face-normal clusters (normals within 2 degrees of the cluster's
/// first face) holding at least 5% of the mesh's faces.
int big_planar_clusters(const assets::MeshCpu& m) {
    std::vector<glm::vec3> fn;
    for (size_t i = 0; i + 2 < m.indices.size(); i += 3) {
        auto& a = m.vertices[m.indices[i]].position; auto& b = m.vertices[m.indices[i+1]].position;
        auto& c = m.vertices[m.indices[i+2]].position;
        fn.push_back(glm::normalize(glm::cross(b - a, c - a)));
    }
    std::vector<glm::vec3> centres; std::vector<int> counts;
    for (auto& n : fn) { bool placed = false;
        for (size_t k = 0; k < centres.size(); ++k) if (glm::dot(n, centres[k]) > std::cos(glm::radians(2.0f))) { ++counts[k]; placed = true; break; }
        if (!placed) { centres.push_back(n); counts.push_back(1); } }
    int big = 0; for (int c : counts) if (c >= int(fn.size() * 0.05)) ++big;
    return big;
}

/// Worst |radius(LOD1 vertex) - radius(nearest-direction LOD0 vertex)|.
float worst_silhouette_error(const assets::MeshCpu& lod0, const assets::MeshCpu& lod1) {
    float worst = 0.0f;
    for (auto& v1 : lod1.vertices) {
        glm::vec3 d = glm::normalize(v1.position); float best = -2, r0 = 0;
        for (auto& v0 : lod0.vertices) { float c = glm::dot(d, glm::normalize(v0.position));
            if (c > best) { best = c; r0 = glm::length(v0.position); } }
        worst = std::max(worst, std::abs(glm::length(v1.position) - r0));
    }
    return worst;
}

}  // namespace

TEST(Shape, Deterministic) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_lods(s[0]), b = rockgen::generate_rock_lods(s[0]);
    ASSERT_EQ(a.size(), b.size());
    for (size_t l = 0; l < a.size(); ++l) {
        ASSERT_EQ(a[l].vertices.size(), b[l].vertices.size());
        EXPECT_EQ(0, std::memcmp(a[l].vertices.data(), b[l].vertices.data(),
                                 a[l].vertices.size() * sizeof(a[l].vertices[0])));
        EXPECT_EQ(a[l].indices, b[l].indices);
    }
}

// LOD0 is normalised to exactly the bound radius; every lower LOD reuses
// LOD0's centre and scale, so it is never larger (and never pops against
// LOD0) but may fall slightly short where it lacks LOD0's extreme vertex.
TEST(Shape, BoundingRadiusIsExact) {
    auto r = rockgen::parse_recipe(kMini);
    for (auto& s : rockgen::expand_recipe(r)) {
        auto lods = rockgen::generate_rock_lods(s);
        ASSERT_FALSE(lods.empty()) << s.id;
        EXPECT_NEAR(rockgen::bounding_radius(lods[0]), 100.0f, 1e-3f) << s.id;
        for (size_t l = 1; l < lods.size(); ++l) {
            EXPECT_LE(rockgen::bounding_radius(lods[l]), 100.0f + 1e-3f) << s.id << " lod" << l;
            EXPECT_GE(rockgen::bounding_radius(lods[l]), 90.0f) << s.id << " lod" << l;
        }
    }
}

// Shared directions sit at the same position in every LOD (no popping): the
// icosphere vertex list at subdivision s is a prefix of the list at s+1, and
// lower LODs reuse LOD0's transform.
TEST(Shape, LowerLodsShareLod0Positions) {
    auto r = rockgen::parse_recipe(kMini);
    for (auto& s : rockgen::expand_recipe(r)) {
        auto lods = rockgen::generate_rock_lods(s);
        ASSERT_EQ(lods.size(), 2u) << s.id;
        const size_t shared = s.fragment ? 42u : 162u;   // 10*4^s+2 vertices at subdivision 1 / 2
        for (size_t i = 0; i < shared; ++i)
            EXPECT_EQ(lods[1].vertices[i].position, lods[0].vertices[i].position) << s.id << " v" << i;
    }
}

TEST(Shape, LodTriangleCounts) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);                   // major, subdivisions 3,2
    ASSERT_EQ(lods.size(), 2u);
    EXPECT_EQ(lods[0].indices.size() / 3, 1280u);
    EXPECT_EQ(lods[1].indices.size() / 3, 320u);
}

TEST(Shape, Distinct) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_lods(s[0])[0], b = rockgen::generate_rock_lods(s[1])[0];
    double diff = 0; // same topology (same subdivision) -> compare radii per vertex
    for (size_t i = 0; i < std::min(a.vertices.size(), b.vertices.size()); ++i)
        diff += std::abs(glm::length(a.vertices[i].position) - glm::length(b.vertices[i].position));
    EXPECT_GT(diff / a.vertices.size(), 2.0);                          // mean radial difference > 2 m
}

TEST(Shape, LodSilhouetteTracksLod0) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    ASSERT_EQ(lods.size(), 2u);
    // Every LOD1 vertex direction's radius is within 8% of LOD0's radius along the nearest LOD0 vertex direction.
    for (auto& v1 : lods[1].vertices) {
        glm::vec3 d = glm::normalize(v1.position); float best = -2, r0 = 0;
        for (auto& v0 : lods[0].vertices) { float c = glm::dot(d, glm::normalize(v0.position));
            if (c > best) { best = c; r0 = glm::length(v0.position); } }
        EXPECT_NEAR(glm::length(v1.position), r0, 0.08f * 100.0f);
    }
}

TEST(Shape, FragmentsHavePlanarFaces) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto m = rockgen::generate_rock_lods(s[2])[0];                   // fragment
    // Count face-normal clusters: faces whose normals agree within 2 degrees and number >= 5% of faces.
    std::vector<glm::vec3> fn;
    for (size_t i = 0; i + 2 < m.indices.size(); i += 3) {
        auto& a = m.vertices[m.indices[i]].position; auto& b = m.vertices[m.indices[i+1]].position;
        auto& c = m.vertices[m.indices[i+2]].position;
        fn.push_back(glm::normalize(glm::cross(b - a, c - a)));
    }
    std::vector<glm::vec3> centres; std::vector<int> counts;
    for (auto& n : fn) { bool placed = false;
        for (size_t k = 0; k < centres.size(); ++k) if (glm::dot(n, centres[k]) > std::cos(glm::radians(2.0f))) { ++counts[k]; placed = true; break; }
        if (!placed) { centres.push_back(n); counts.push_back(1); } }
    int big = 0; for (int c : counts) if (c >= int(fn.size() * 0.05)) ++big;
    EXPECT_GE(big, 2); EXPECT_LE(big, 4);
}

TEST(Shape, OutwardWinding) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto m = rockgen::generate_rock_lods(s[0])[0];
    int outward = 0, total = 0;
    for (size_t i = 0; i + 2 < m.indices.size(); i += 3, ++total) {
        auto& a = m.vertices[m.indices[i]].position; auto& b = m.vertices[m.indices[i+1]].position;
        auto& c = m.vertices[m.indices[i+2]].position;
        if (glm::dot(glm::cross(b - a, c - a), (a + b + c) / 3.0f) > 0) ++outward;
    }
    EXPECT_GT(outward, total * 0.97);   // CCW outward, as glTF requires
}

// Ported from the branch's AsteroidGen.NoTriangleStraddlesTheUvSeam /
// UvsAreInRange. A triangle spanning u~0.98..0.02 interpolates backwards
// through the whole texture, smearing a band down the rock. Seam-straddling
// vertices are duplicated with u += 1.0 (textures sample GL_REPEAT, so
// u=1.02 is the same texel as u=0.02) so no triangle spans more than half the
// u range. u may therefore exceed 1.0 -- do not tighten it back to [0,1].
TEST(Shape, UvSeamSplit) {
    auto r = rockgen::parse_recipe(kMini);
    for (auto& s : rockgen::expand_recipe(r)) {
        auto lods = rockgen::generate_rock_lods(s);
        ASSERT_FALSE(lods.empty()) << s.id;
        for (size_t l = 0; l < lods.size(); ++l) {
            const auto& m = lods[l];
            ASSERT_FALSE(m.indices.empty()) << s.id << " lod" << l;
            for (const auto& v : m.vertices) {
                EXPECT_GE(v.uv.x, 0.0f) << s.id << " lod" << l;
                EXPECT_LT(v.uv.x, 2.0f) << s.id << " lod" << l;
                EXPECT_GE(v.uv.y, 0.0f) << s.id << " lod" << l;
                EXPECT_LE(v.uv.y, 1.0f) << s.id << " lod" << l;
            }
            for (size_t i = 0; i < m.indices.size(); i += 3) {
                const float u0 = m.vertices[m.indices[i    ]].uv.x;
                const float u1 = m.vertices[m.indices[i + 1]].uv.x;
                const float u2 = m.vertices[m.indices[i + 2]].uv.x;
                const float span = std::max({u0, u1, u2}) - std::min({u0, u1, u2});
                EXPECT_LE(span, 0.5f) << s.id << " lod" << l << " triangle " << i / 3;
            }
        }
    }
}

TEST(Shape, EveryFragmentHasPlanarFaces) {
    auto r = rockgen::parse_recipe(kFragmentSweep); auto specs = rockgen::expand_recipe(r);
    ASSERT_EQ(specs.size(), 24u);
    for (auto& s : specs) {
        const int big = big_planar_clusters(rockgen::generate_rock_lods(s)[0]);
        EXPECT_GE(big, 2) << s.id;
        EXPECT_LE(big, 4) << s.id;
    }
}

TEST(Shape, EveryFragmentLodSilhouetteTracksLod0) {
    auto r = rockgen::parse_recipe(kFragmentSweep); auto specs = rockgen::expand_recipe(r);
    ASSERT_EQ(specs.size(), 24u);
    for (auto& s : specs) {
        auto lods = rockgen::generate_rock_lods(s);
        ASSERT_EQ(lods.size(), 2u) << s.id;
        EXPECT_LE(worst_silhouette_error(lods[0], lods[1]), 0.08f * 100.0f) << s.id;
    }
}
