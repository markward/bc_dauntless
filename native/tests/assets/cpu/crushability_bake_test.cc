#include <gtest/gtest.h>
#include <cmath>
#include <assets/crushability_bake.h>
#include <assets/mesh.h>

using assets::crushability_from_thickness;

TEST(CrushabilityMapping, ThinIsHighThickIsLow) {
    // ref = 4.0: thickness 0 -> 1, thickness >= ref -> 0, linear between.
    EXPECT_FLOAT_EQ(crushability_from_thickness(0.0f, 4.0f), 1.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(4.0f, 4.0f), 0.0f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 4.0f), 0.75f);
    EXPECT_FLOAT_EQ(crushability_from_thickness(2.0f, 4.0f), 0.5f);
}

TEST(CrushabilityMapping, ClampsAndHandlesDegenerateRef) {
    EXPECT_FLOAT_EQ(crushability_from_thickness(10.0f, 4.0f), 0.0f);  // beyond ref -> clamp 0
    EXPECT_FLOAT_EQ(crushability_from_thickness(-1.0f, 4.0f), 1.0f);  // negative -> clamp 1
    EXPECT_FLOAT_EQ(crushability_from_thickness(1.0f, 0.0f), 0.0f);   // ref<=0 -> 0 (uncrushable)
}

namespace {
// Two facing quads: a small top quad at z=0 (x,y in [0,10]) and a larger
// bottom quad at z=-1 (x,y in [-5,15]). The bottom overhangs the top so a
// ray straight down from any top point lands in the bottom's interior
// (avoids fragile edge/corner hits).
assets::MeshCpu make_facing_quads() {
    assets::MeshCpu m;
    auto v = [](float x, float y, float z, glm::vec3 n) {
        assets::MeshCpu::Vertex vert;
        vert.position = {x, y, z};
        vert.normal = n;
        return vert;
    };
    const glm::vec3 up{0, 0, 1}, down{0, 0, -1};
    // 0..3 top quad (normal +z), 4..7 bottom quad (normal -z)
    m.vertices = {
        v(0, 0, 0, up),  v(10, 0, 0, up),  v(10, 10, 0, up),  v(0, 10, 0, up),
        v(-5, -5, -1, down), v(15, -5, -1, down),
        v(15, 15, -1, down), v(-5, 15, -1, down),
    };
    m.indices = {
        0, 1, 2,  0, 2, 3,        // top
        4, 5, 6,  4, 6, 7,        // bottom
    };
    return m;
}
}  // namespace

TEST(BakeCrushability, ThinFaceCrushesMoreThanNoHitEdge) {
    assets::MeshCpu m = make_facing_quads();
    assets::bake_crushability(m);  // default params

    // Top-quad vertices (normal +z) cast down, hit the overhanging bottom at
    // thickness 1 (thin) -> crushability well above the 0.5 fallback.
    for (std::size_t i = 0; i < 4; ++i) {
        EXPECT_GT(m.vertices[i].crushability, 0.5f)
            << "top vertex " << i << " should read as thin/crushable";
    }
    // Bottom-quad corners (normal -z) cast up but the smaller top quad does not
    // cover them, so the ray misses -> no_hit_value (0.5).
    for (std::size_t i = 4; i < 8; ++i) {
        EXPECT_FLOAT_EQ(m.vertices[i].crushability, 0.5f)
            << "bottom corner " << i << " should fall back to no_hit_value";
    }
}

TEST(BakeCrushability, ZeroNormalGetsNoHitValue) {
    assets::MeshCpu m = make_facing_quads();
    m.vertices[0].normal = {0, 0, 0};  // degenerate normal
    assets::bake_crushability(m);
    EXPECT_FLOAT_EQ(m.vertices[0].crushability, 0.5f);
}

TEST(BakeCrushability, EmptyMeshDoesNotCrash) {
    assets::MeshCpu m;  // no vertices, no indices
    assets::bake_crushability(m);  // must not crash
    EXPECT_TRUE(m.vertices.empty());
    EXPECT_TRUE(m.indices.empty());
}

TEST(BakeCrushability, NoTrianglesGivesAllNoHitValue) {
    // Vertices present but no triangles: no ray can hit, so every vertex
    // gets no_hit_value (honoring a custom value).
    assets::MeshCpu m;
    auto vert = [](float x, float y, float z) {
        assets::MeshCpu::Vertex v;
        v.position = {x, y, z};
        v.normal = {0, 0, 1};
        return v;
    };
    m.vertices = {vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0)};
    // indices intentionally left empty (no triangles)
    assets::CrushabilityParams p;
    p.no_hit_value = 0.3f;
    assets::bake_crushability(m, p);
    for (const auto& v : m.vertices) {
        EXPECT_FLOAT_EQ(v.crushability, 0.3f);
    }
}

TEST(BakeCrushability, RespectsCustomNoHitValue) {
    assets::MeshCpu m = make_facing_quads();
    assets::CrushabilityParams p;
    p.no_hit_value = 0.1f;
    assets::bake_crushability(m, p);
    EXPECT_FLOAT_EQ(m.vertices[4].crushability, 0.1f);  // a missing bottom corner
}

TEST(ProbeThickness, HitsOppositeSurface) {
    const assets::MeshCpu m = make_facing_quads();
    // From the centre of the top quad, straight down, must hit the bottom at t=1.
    const float t = assets::probe_thickness(m, {5, 5, 0}, {0, 0, -1}, 100.0f);
    EXPECT_NEAR(t, 1.0f, 1e-4f);
}

TEST(ProbeThickness, MissReturnsInfinity) {
    const assets::MeshCpu m = make_facing_quads();
    // From the top quad centre, straight UP (away from all geometry): no hit.
    const float t = assets::probe_thickness(m, {5, 5, 0}, {0, 0, 1}, 100.0f);
    EXPECT_TRUE(std::isinf(t));
}
