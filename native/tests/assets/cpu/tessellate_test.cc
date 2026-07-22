#include <gtest/gtest.h>

#include <assets/tessellate.h>
#include <assets/mesh.h>

#include <glm/glm.hpp>

#include <cmath>

using assets::MeshCpu;
using assets::tessellate_phong;

namespace {

MeshCpu::Vertex vert(glm::vec3 pos, glm::vec3 nrm,
                     glm::u8vec4 bidx = {0, 0, 0, 0},
                     glm::u8vec4 bwt = {255, 0, 0, 0}) {
    MeshCpu::Vertex v;
    v.position = pos;
    v.normal = glm::normalize(nrm);
    v.bone_indices = bidx;
    v.bone_weights = bwt;
    return v;
}

float max_abs_z(const MeshCpu& m) {
    float z = 0.0f;
    for (const auto& v : m.vertices) z = std::max(z, std::abs(v.position.z));
    return z;
}

}  // namespace

// A single flat triangle in z=0 with +z normals: one level = 4 triangles.
TEST(TessellatePhong, QuadruplesTriangleCount) {
    MeshCpu m;
    m.vertices = {vert({0, 0, 0}, {0, 0, 1}),
                  vert({1, 0, 0}, {0, 0, 1}),
                  vert({0, 1, 0}, {0, 0, 1})};
    m.indices = {0, 1, 2};
    MeshCpu t = tessellate_phong(m, 1.0f);
    EXPECT_EQ(t.indices.size(), m.indices.size() * 4u);
}

// Rigid (single-bone) verts must keep their exact binding — no candy-wrapper.
TEST(TessellatePhong, RigidBonePreserved) {
    MeshCpu m;
    const glm::u8vec4 idx{7, 0, 0, 0}, wt{255, 0, 0, 0};
    m.vertices = {vert({0, 0, 0}, {0, 0, 1}, idx, wt),
                  vert({1, 0, 0}, {0, 0, 1}, idx, wt),
                  vert({0, 1, 0}, {0, 0, 1}, idx, wt)};
    m.indices = {0, 1, 2};
    MeshCpu t = tessellate_phong(m, 1.0f);
    for (const auto& v : t.vertices) {
        EXPECT_EQ(v.bone_indices[0], 7);
        EXPECT_EQ(v.bone_weights[0], 255);
    }
}

// Phong projection of a planar patch is a no-op: flat in => flat out.
TEST(TessellatePhong, FlatSurfaceStaysFlat) {
    MeshCpu m;
    m.vertices = {vert({0, 0, 0}, {0, 0, 1}),
                  vert({1, 0, 0}, {0, 0, 1}),
                  vert({0, 1, 0}, {0, 0, 1})};
    m.indices = {0, 1, 2};
    MeshCpu t = tessellate_phong(m, 1.0f);
    EXPECT_LT(max_abs_z(t), 1e-5f);
}

// Two triangles sharing an interior edge produce ONE shared midpoint there,
// so the whole patch stays watertight (4 verts -> 9, not 4 -> 10).
TEST(TessellatePhong, SharedInteriorEdgeIsWatertight) {
    MeshCpu m;
    m.vertices = {vert({0, 0, 0}, {0, 0, 1}),
                  vert({1, 0, 0}, {0, 0, 1}),
                  vert({0, 1, 0}, {0, 0, 1}),
                  vert({1, 1, 0}, {0, 0, 1})};
    m.indices = {0, 1, 2, 2, 1, 3};  // share edge (1,2)
    MeshCpu t = tessellate_phong(m, 1.0f);
    EXPECT_EQ(t.vertices.size(), 9u);
}

// A genuine open boundary edge (used by a single triangle) must stay pinned
// flat even with tilted normals — this is what keeps separate shapes from
// cracking apart at their shared seam.
TEST(TessellatePhong, OpenBoundaryEdgeStaysPinned) {
    MeshCpu m;
    // Curved single triangle: all three edges are open boundaries.
    m.vertices = {vert({-1, 0, 0}, {-1, 0, 1}),
                  vert({1, 0, 0}, {1, 0, 1}),
                  vert({0, 1, 0}, {0, 1, 1})};
    m.indices = {0, 1, 2};
    MeshCpu t = tessellate_phong(m, 1.0f);
    EXPECT_LT(max_abs_z(t), 1e-5f) << "open boundary midpoints must not bulge";
}

// THE FIX: two triangles sharing a spatial edge via DUPLICATED verts (a UV
// seam) must be treated as an interior edge and ROUNDED, not pinned flat.
// Indices differ across the seam; only position-keyed boundary detection sees
// it as interior. Symmetric tilted normals bulge the seam midpoint to z~0.5.
TEST(TessellatePhong, UvSeamAcrossInteriorEdgeIsRoundedNotPinned) {
    const glm::vec3 p1{0, 0, 0}, p2{2, 0, 0};
    const glm::vec3 n1{-1, 0, 1}, n2{1, 0, 1};  // symmetric inward tilt
    MeshCpu m;
    m.vertices = {
        vert({1, -1, 0}, {0, 0, 1}),  // 0: triangle-A apex (flat normal)
        vert(p1, n1),                 // 1: A's p1
        vert(p2, n2),                 // 2: A's p2
        vert(p1, n1),                 // 3: B's p1 (UV-seam duplicate of 1)
        vert(p2, n2),                 // 4: B's p2 (UV-seam duplicate of 2)
        vert({1, 1, 0}, {0, 0, 1}),   // 5: triangle-B apex (flat normal)
    };
    m.indices = {0, 1, 2, 3, 4, 5};  // A=(0,1,2), B=(3,4,5) share edge p1-p2
    MeshCpu t = tessellate_phong(m, 1.0f);
    // The only edge shared across both triangles is p1-p2. If it is rounded,
    // its midpoint bulges to ~+0.5 in z; if pinned (the bug), everything is
    // flat because every other edge is a genuine boundary.
    EXPECT_GT(max_abs_z(t), 0.4f)
        << "UV-seam interior edge was pinned flat instead of rounded";
}

// Skinned midpoints blend the two endpoints' influences (top-4, renormalized).
TEST(TessellatePhong, SkinnedWeightsBlendedAtMidpoint) {
    MeshCpu m;
    m.vertices = {vert({0, 0, 0}, {0, 0, 1}, {5, 0, 0, 0}, {255, 0, 0, 0}),
                  vert({1, 0, 0}, {0, 0, 1}, {9, 0, 0, 0}, {255, 0, 0, 0}),
                  vert({0, 1, 0}, {0, 0, 1}, {5, 0, 0, 0}, {255, 0, 0, 0})};
    m.indices = {0, 1, 2};
    MeshCpu t = tessellate_phong(m, 1.0f);
    // Find the midpoint of edge (0,1): it must carry both bone 5 and bone 9.
    bool found = false;
    for (const auto& v : t.vertices) {
        int w5 = 0, w9 = 0, total = 0;
        for (int k = 0; k < 4; ++k) {
            total += v.bone_weights[k];
            if (v.bone_weights[k] == 0) continue;
            if (v.bone_indices[k] == 5) w5 = v.bone_weights[k];
            if (v.bone_indices[k] == 9) w9 = v.bone_weights[k];
        }
        if (w5 > 0 && w9 > 0) {
            found = true;
            EXPECT_NEAR(w5, 127, 2);
            EXPECT_NEAR(w9, 127, 2);
            EXPECT_EQ(total, 255) << "blended weights must renormalize to 255";
        }
    }
    EXPECT_TRUE(found) << "no midpoint blended bones 5 and 9";
}
