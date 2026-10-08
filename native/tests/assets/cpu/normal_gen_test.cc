#include <gtest/gtest.h>

#include "normal_gen.h"

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <vector>

using assets::MeshCpu;
using assets::detail::generate_smooth_normals;
using assets::detail::generate_normals_across_shapes;
using assets::detail::kSetNormalCreaseDeg;
using assets::detail::NormalGenShape;

namespace {

MeshCpu::Vertex at(glm::vec3 p, glm::u8vec4 colour = {255, 255, 255, 255}) {
    MeshCpu::Vertex v;
    v.position = p;
    v.color = colour;
    return v;
}

// Two triangles folded along the edge (0,0,0)-(1,0,0). Triangle A lies in
// the z=0 plane (normal +Z); triangle B is tilted by `fold_deg` about X.
// shared=true: the hinge vertices are shared by index. shared=false: each
// triangle has its own copies (a soup), optionally differing in colour.
MeshCpu fold(float fold_deg, bool shared,
             glm::u8vec4 b_colour = {255, 255, 255, 255}) {
    const float a = glm::radians(fold_deg);
    const glm::vec3 h0{0, 0, 0}, h1{1, 0, 0};
    const glm::vec3 pa{0.5f, -1, 0};
    const glm::vec3 pb{0.5f, std::cos(a), std::sin(a)};
    MeshCpu m;
    if (shared) {
        m.vertices = {at(h0), at(h1), at(pa), at(pb)};
        m.indices = {0, 2, 1, 0, 1, 3};
    } else {
        m.vertices = {at(h0), at(h1), at(pa),
                      at(h0, b_colour), at(h1, b_colour), at(pb, b_colour)};
        m.indices = {0, 2, 1, 3, 4, 5};
    }
    return m;
}

glm::vec3 corner_normal(const MeshCpu& m, int tri, int corner) {
    return m.vertices[m.indices[tri * 3 + corner]].normal;
}

glm::vec3 face_normal(const MeshCpu& m, int tri) {
    const auto& p0 = m.vertices[m.indices[tri * 3 + 0]].position;
    const auto& p1 = m.vertices[m.indices[tri * 3 + 1]].position;
    const auto& p2 = m.vertices[m.indices[tri * 3 + 2]].position;
    return glm::normalize(glm::cross(p1 - p0, p2 - p0));
}

// The two hinge corners of triangle `tri` (corner 0 is h0 in both layouts).
float hinge_dot_to_face(const MeshCpu& m, int tri) {
    return glm::dot(glm::normalize(corner_normal(m, tri, 0)), face_normal(m, tri));
}

}  // namespace

TEST(NormalGen, ShallowFoldSharedByIndexIsSmoothed) {
    MeshCpu m = fold(20.0f, /*shared=*/true);
    generate_smooth_normals(m, 40.0f);
    // Smoothed: the hinge normal sits between the faces, ~10 deg off each.
    EXPECT_NEAR(hinge_dot_to_face(m, 0), std::cos(glm::radians(10.0f)), 1e-3);
    EXPECT_NEAR(hinge_dot_to_face(m, 1), std::cos(glm::radians(10.0f)), 1e-3);
}

TEST(NormalGen, SharpFoldSharedByIndexIsSplitIntoFlatFaces) {
    MeshCpu m = fold(90.0f, /*shared=*/true);
    generate_smooth_normals(m, 40.0f);
    EXPECT_NEAR(hinge_dot_to_face(m, 0), 1.0f, 1e-4);
    EXPECT_NEAR(hinge_dot_to_face(m, 1), 1.0f, 1e-4);
    EXPECT_GT(m.vertices.size(), 4u);  // hinge vertices were split
}

TEST(NormalGen, ShallowFoldInASoupSmoothsAcrossColourSplit) {
    MeshCpu m = fold(20.0f, /*shared=*/false, /*b_colour=*/{10, 20, 30, 255});
    generate_smooth_normals(m, 40.0f);
    EXPECT_NEAR(hinge_dot_to_face(m, 0), std::cos(glm::radians(10.0f)), 1e-3);
    EXPECT_NEAR(hinge_dot_to_face(m, 1), std::cos(glm::radians(10.0f)), 1e-3);
}

TEST(NormalGen, IdenticalTwinVerticesAreAnAuthoredHardEdge) {
    MeshCpu m = fold(20.0f, /*shared=*/false);  // same colour, same UV
    generate_smooth_normals(m, 40.0f);
    EXPECT_NEAR(hinge_dot_to_face(m, 0), 1.0f, 1e-4);
    EXPECT_NEAR(hinge_dot_to_face(m, 1), 1.0f, 1e-4);
}

TEST(NormalGen, SplitVerticesCarryTheirExtraUvs) {
    MeshCpu m = fold(90.0f, /*shared=*/true);
    m.extra_uvs.push_back({{0, 0}, {1, 0}, {0, 1}, {1, 1}});
    generate_smooth_normals(m, 40.0f);
    ASSERT_EQ(m.extra_uvs.size(), 1u);
    EXPECT_EQ(m.extra_uvs[0].size(), m.vertices.size());
}

TEST(NormalGen, EveryNormalIsUnitLength) {
    MeshCpu m = fold(20.0f, /*shared=*/true);
    generate_smooth_normals(m, 40.0f);
    for (const auto& v : m.vertices)
        EXPECT_NEAR(glm::length(v.normal), 1.0f, 1e-4);
}

TEST(NormalGen, MixedWindingShallowFoldIsSmoothedPerOwnFace) {
    MeshCpu m = fold(20.0f, /*shared=*/true);
    m.indices = {0, 2, 1, 0, 3, 1};  // B wound the other way (normal flipped)
    generate_smooth_normals(m, 40.0f);
    // Still smoothed, and each corner leans the same way as its own face.
    EXPECT_NEAR(hinge_dot_to_face(m, 0), std::cos(glm::radians(10.0f)), 1e-3);
    EXPECT_NEAR(hinge_dot_to_face(m, 1), std::cos(glm::radians(10.0f)), 1e-3);
}

// A fan of three faces around the origin: A and B are 5 deg apart, C is
// 38 deg from B and so 43 deg from A. With a 40 deg crease, A-B and B-C are
// both smooth edges, so all three belong to ONE smoothing group and the
// normal must be continuous across the A-B edge. A per-face "neighbours
// within crease of me" rule lets C into B's average but not A's, and the
// A-B edge shows a seam even though it is nearly flat.
TEST(NormalGen, SmoothEdgeIsContinuousThroughAChainedFan) {
    auto dir = [](float deg) {
        const float a = glm::radians(deg);
        return glm::vec3(0.0f, std::cos(a), std::sin(a));
    };
    const glm::vec3 o{0, 0, 0}, x{1, 0, 0};
    // Edges around the hinge axis X: A spans dir(-90)..dir(0) style wedges.
    // Use half-planes hinged on the X axis at angles 0, 5 and 43 deg.
    MeshCpu m;
    m.vertices = {at(o), at(x), at({0.5f, -1, 0}),        // A: z=0 plane
                  at(dir(5.0f) + glm::vec3(0.5f, 0, 0))};  // B tip
    m.indices = {0, 2, 1, 0, 1, 3};
    // C shares the edge (o, B tip) with B, folded 38 deg further.
    const glm::vec3 bt = m.vertices[3].position;
    const glm::vec3 axis = glm::normalize(bt - o);
    const glm::vec3 nb = glm::normalize(glm::cross(x - o, bt - o));
    const glm::vec3 inplane = glm::normalize(glm::cross(nb, axis));
    const float f = glm::radians(38.0f);
    const glm::vec3 ct = o + axis * 0.5f
        + (inplane * std::cos(f) + nb * std::sin(f)) * 0.8f;
    m.vertices.push_back(at(ct));
    m.indices.insert(m.indices.end(), {0, 3, 4});
    // Preconditions: the fixture really is the chained case.
    const auto deg = [](glm::vec3 a, glm::vec3 b) {
        return glm::degrees(std::acos(std::fabs(glm::dot(a, b))));
    };
    ASSERT_LT(deg(face_normal(m, 0), face_normal(m, 1)), 40.0f);
    ASSERT_LT(deg(face_normal(m, 1), face_normal(m, 2)), 40.0f);
    ASSERT_GT(deg(face_normal(m, 0), face_normal(m, 2)), 40.0f);
    generate_smooth_normals(m, 40.0f);
    const glm::vec3 na = glm::normalize(corner_normal(m, 0, 0));  // A at o
    const glm::vec3 nB = glm::normalize(corner_normal(m, 1, 0));  // B at o
    EXPECT_GT(glm::dot(na, nB), 0.9999f);
}

// Twins are judged on the SOURCE (float) vertex colours. BC bakes lighting
// into colours that differ by less than one 8-bit step at many split
// vertices; quantised they look identical, but the split was a colour
// split, not a hard edge (DBridge "D walls 1": 0 float twins, 721 u8 twins).
TEST(NormalGen, TwinsAreJudgedOnSourceColoursNotQuantised) {
    MeshCpu m = fold(20.0f, /*shared=*/false);  // u8 colours identical
    std::vector<glm::vec4> source(m.vertices.size(), glm::vec4(0.5f));
    for (int i = 3; i < 6; ++i) source[i] = glm::vec4(0.5f + 1e-4f);  // B differs
    generate_smooth_normals(m, 40.0f, source);
    EXPECT_NEAR(hinge_dot_to_face(m, 0), std::cos(glm::radians(10.0f)), 1e-3);
}

// ── T-junction repair ──────────────────────────────────────────────────────
// Long triangle L spans x 0..2 along y=0 (below the line). Two small
// triangles above share the T vertex (1,0,0), which lies INSIDE L's edge.
namespace {
MeshCpu t_junction() {
    MeshCpu m;
    auto uv = [](MeshCpu::Vertex v, glm::vec2 t) { v.uv = t; return v; };
    m.vertices = {uv(at({0, 0, 0}), {0, 0}), uv(at({2, 0, 0}), {1, 0}),
                  uv(at({1, -1, 0}), {0.5f, 1}),                     // L
                  at({0, 0, 0}), at({1, 0, 0}), at({0.5f, 1, 0}),    // S1
                  at({1, 0, 0}), at({2, 0, 0}), at({1.5f, 1, 0})};   // S2
    m.indices = {0, 2, 1, 3, 4, 5, 6, 7, 8};
    return m;
}

bool any_vertex_inside_an_edge(const MeshCpu& m) {
    for (std::size_t t = 0; t < m.indices.size() / 3; ++t)
        for (int k = 0; k < 3; ++k) {
            const glm::vec3 a = m.vertices[m.indices[t * 3 + k]].position;
            const glm::vec3 b = m.vertices[m.indices[t * 3 + (k + 1) % 3]].position;
            const glm::vec3 ab = b - a;
            for (const auto& v : m.vertices) {
                const float u = glm::dot(v.position - a, ab) / glm::dot(ab, ab);
                if (u <= 1e-3f || u >= 1.0f - 1e-3f) continue;
                if (glm::length(v.position - a - u * ab) < 1e-4f) return true;
            }
        }
    return false;
}
}  // namespace

TEST(TJunctionRepair, LongEdgeIsSplitAtTheVertexLyingOnIt) {
    MeshCpu m = t_junction();
    std::vector<glm::vec4> src;
    assets::detail::repair_t_junctions(m, src);
    EXPECT_EQ(m.indices.size() / 3, 4u);  // L became two triangles
    EXPECT_FALSE(any_vertex_inside_an_edge(m));
}

TEST(TJunctionRepair, InsertedVertexInterpolatesTheSplitTrianglesAttributes) {
    MeshCpu m = t_junction();
    std::vector<glm::vec4> src(m.vertices.size(), glm::vec4(0.0f));
    src[0] = glm::vec4(0.2f);
    src[1] = glm::vec4(0.6f);
    assets::detail::repair_t_junctions(m, src);
    // L's new corner at (1,0,0) carries L's mapping (uv midway between its
    // (0,0) and (1,0)), NOT the small triangles' vertex there.
    bool found = false;
    for (std::size_t i = 9; i < m.vertices.size(); ++i) {
        if (glm::length(m.vertices[i].position - glm::vec3(1, 0, 0)) > 1e-6f) continue;
        found = true;
        EXPECT_NEAR(m.vertices[i].uv.x, 0.5f, 1e-5f);
        EXPECT_NEAR(m.vertices[i].uv.y, 0.0f, 1e-5f);
        EXPECT_NEAR(src[i].x, 0.4f, 1e-5f);
    }
    EXPECT_TRUE(found);
    EXPECT_EQ(src.size(), m.vertices.size());
}

TEST(TJunctionRepair, ExtraUvsGrowWithTheVertices) {
    MeshCpu m = t_junction();
    m.extra_uvs.push_back(std::vector<glm::vec2>(m.vertices.size(), {0, 0}));
    std::vector<glm::vec4> src;
    assets::detail::repair_t_junctions(m, src);
    EXPECT_EQ(m.extra_uvs[0].size(), m.vertices.size());
}

// Only points on a triangle's ORIGINAL edges are T-junctions. A vertex that
// happens to sit on the diagonal created by a split lies inside the face
// (overlapping geometry), and splitting there cascades (DBridge "wall inset
// main" grew 494 -> 844 tris and hit the split cap).
TEST(TJunctionRepair, NeverSplitsAtAPointOnAnInsertedDiagonal) {
    MeshCpu m;
    m.vertices = {at({0, 0, 0}), at({2, 0, 0}), at({1, -2, 0}),          // L
                  at({0, 0, 0}), at({1, 0, 0}), at({0.5f, 1, 0}),        // S1
                  at({1, 0, 0}), at({2, 0, 0}), at({1.5f, 1, 0}),        // S2
                  at({1, -1, 0}), at({5, 5, 5}), at({6, 5, 5})};         // far
    m.indices = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
    std::vector<glm::vec4> src;
    assets::detail::repair_t_junctions(m, src);
    EXPECT_EQ(m.indices.size() / 3, 5u);  // only L's T-junction split
}

// ── Weighting ──────────────────────────────────────────────────────────────
// A big flat face (z=0) beside a small bevel face folded 30 deg, sharing an
// edge. Corner contributions are weighted by face AREA, so the big face keeps
// its own corners (nearly) flat. Angle weighting let the bevel drag them: up
// to 17 deg on DBridge's large "D walls 1" triangles, an ~18% downlight dip.
namespace {
MeshCpu big_face_with_bevel() {
    // Big face: long and thin, so its corner angle at the origin is small
    // (5.7 deg) while its area is large (5). The bevel shares the edge
    // origin->(1,0,0) with a wide corner angle (56 deg) but small area (0.4)
    // — the shape of a low-poly wall triangle beside a fillet fan.
    const float a = glm::radians(30.0f);
    MeshCpu m;
    m.vertices = {at({0, 0, 0}), at({1, 0, 0}), at({100, -10, 0}),
                  at({0.5f, 0.8f * std::cos(a), 0.8f * std::sin(a)})};
    m.indices = {0, 2, 1, 0, 1, 3};
    return m;
}
float big_face_corner_drag_deg(const MeshCpu& m) {
    return glm::degrees(std::acos(std::min(1.0f,
        glm::dot(glm::normalize(corner_normal(m, 0, 0)), face_normal(m, 0)))));
}

// Two triangles spanning [x0, x0+1] x [0,1] at z=0, normals zero.
MeshCpu quad_xy(float x0) {
    MeshCpu m;
    m.vertices = {at({x0, 0, 0}), at({x0 + 1, 0, 0}),
                  at({x0 + 1, 1, 0}), at({x0, 1, 0})};
    m.indices = {0, 1, 2, 0, 2, 3};
    return m;
}
}  // namespace

TEST(NormalGen, AreaWeightingKeepsABigFaceFlatBesideASmallBevel) {
    MeshCpu m = big_face_with_bevel();
    generate_smooth_normals(m, 40.0f);
    EXPECT_LT(big_face_corner_drag_deg(m), 3.0f);
}

// ── Across shapes ──────────────────────────────────────────────────────────
// Two SHAPES meeting at a seam, each in its own node frame. Normals are
// generated in the shared model space, so the seam smooths like any edge
// (DBridge archway: the "D walls 1" header meets the turbolift top).
TEST(NormalGenAcross, SeamBetweenTwoShapesIsSmoothed) {
    MeshCpu folded = fold(20.0f, /*shared=*/true);
    MeshCpu a, b;
    a.vertices = {folded.vertices[0], folded.vertices[1], folded.vertices[2]};
    a.indices = {0, 2, 1};
    // B's node frame is translated by +5 in X: its local verts are -5.
    const glm::mat4 b_to_model = glm::translate(glm::mat4(1.0f), glm::vec3(5, 0, 0));
    b.vertices = {folded.vertices[0], folded.vertices[1], folded.vertices[3]};
    for (auto& v : b.vertices) v.position -= glm::vec3(5, 0, 0);
    b.indices = {0, 1, 2};
    std::vector<NormalGenShape> shapes{{&a, glm::mat4(1.0f), {}}, {&b, b_to_model, {}}};
    generate_normals_across_shapes(shapes, 40.0f);
    EXPECT_NEAR(hinge_dot_to_face(a, 0), std::cos(glm::radians(10.0f)), 1e-2);
    EXPECT_NEAR(hinge_dot_to_face(b, 0), std::cos(glm::radians(10.0f)), 1e-2);
    // Positions stay in each mesh's own frame.
    EXPECT_NEAR(b.vertices[b.indices[0]].position.x, -5.0f, 1e-5f);
}

// Generation only sees the shapes it is handed; the caller decides which.
TEST(NormalGenAcross, ShapesNotPassedInAreLeftAlone) {
    MeshCpu a = fold(20.0f, /*shared=*/true);
    for (auto& v : a.vertices) v.normal = {0, 1, 0};
    MeshCpu b = quad_xy(2.0f);
    std::vector<NormalGenShape> shapes{{&b, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, 40.0f);
    for (const auto& v : a.vertices) EXPECT_EQ(v.normal, glm::vec3(0, 1, 0));
}

TEST(NormalGenAcross, ShapesKeepTheirOwnExtraUvSetCount) {
    // Shape a carries one extra UV set, shape b none. The joint pass must
    // hand each back with exactly its own channel count -- no padding, no
    // bookkeeping channels left behind.
    MeshCpu a = quad_xy(0.0f);  a.extra_uvs.push_back(std::vector<glm::vec2>(a.vertices.size(), {0.5f, 0.5f}));
    MeshCpu b = quad_xy(1.0f);
    std::vector<NormalGenShape> shapes{{&a, glm::mat4(1.0f), {}}, {&b, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, kSetNormalCreaseDeg);
    ASSERT_EQ(a.extra_uvs.size(), 1u);
    EXPECT_EQ(a.extra_uvs[0].size(), a.vertices.size());
    EXPECT_TRUE(b.extra_uvs.empty());
}

TEST(NormalGenAcross, AuthoredNormalsInAMixedModelAreUntouched) {
    // build_model passes only normal-less shapes; this pins the contract the
    // model builder relies on: a shape with normals that IS adjacent to
    // generated ones keeps its normals bit-for-bit.
    MeshCpu authored = quad_xy(0.0f);
    for (auto& v : authored.vertices) v.normal = glm::normalize(glm::vec3(0.3f, 0.0f, 1.0f));
    const MeshCpu before = authored;
    MeshCpu bare = quad_xy(1.0f);
    std::vector<NormalGenShape> shapes{{&bare, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, kSetNormalCreaseDeg);
    ASSERT_EQ(authored.vertices.size(), before.vertices.size());
    for (std::size_t i = 0; i < authored.vertices.size(); ++i)
        EXPECT_EQ(authored.vertices[i].normal, before.vertices[i].normal);
}

// Both triangles sharing an edge get split at the same T point, walking the
// edge in opposite directions. The inserted positions must be BIT-identical,
// or the shared edge cracks (single-pixel specks along the DBridge console
// frame once cross-shape points started splitting wall triangles).
TEST(TJunctionRepair, BothSidesOfASharedEdgeInsertTheSameBits) {
    const glm::vec3 a{0.1f, 0.7f, 0.3f}, b{10.3f, -2.9f, 5.7f};
    MeshCpu m;
    // Interior edge a-b shared by two triangles (opposite directions), and a
    // separate triangle with a vertex lying on that edge.
    const glm::vec3 p = a + (b - a) * 0.3713f;
    m.vertices = {at(a), at(b), at({3, 9, 1}),
                  at(b), at(a), at({4, -8, 2}),
                  at(p), at(p + glm::vec3(0, 0, 3)), at(p + glm::vec3(1, 0, 3))};
    m.indices = {0, 1, 2, 3, 4, 5, 6, 7, 8};
    std::vector<glm::vec4> src;
    assets::detail::repair_t_junctions(m, src);
    std::vector<glm::vec3> inserted;
    for (std::size_t i = 9; i < m.vertices.size(); ++i) inserted.push_back(m.vertices[i].position);
    ASSERT_EQ(inserted.size(), 2u);
    EXPECT_EQ(inserted[0], inserted[1]);
}

// The same, through the cross-shape path: the output position comes from the
// interpolated LOCAL position, which must also be order-independent.
TEST(NormalGenAcross, SharedEdgeSplitIsBitIdenticalOnBothSides) {
    const glm::vec3 a{0.1f, 0.7f, 0.3f}, b{10.3f, -2.9f, 5.7f};
    const glm::vec3 p = a + (b - a) * 0.3713f;
    MeshCpu wall, trim;
    wall.vertices = {at(a), at(b), at({3, 9, 1}), at(b), at(a), at({4, -8, 2})};
    wall.indices = {0, 1, 2, 3, 4, 5};
    trim.vertices = {at(p), at(p + glm::vec3(0, 0, 3)), at(p + glm::vec3(1, 0, 3))};
    trim.indices = {0, 1, 2};
    std::vector<NormalGenShape> shapes{{&wall, glm::mat4(1.0f), {}},
                                       {&trim, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, 40.0f);
    // Every wall vertex near p must have exactly one distinct position.
    std::vector<glm::vec3> near_p;
    for (const auto& v : wall.vertices)
        if (glm::length(v.position - p) < 1e-3f) near_p.push_back(v.position);
    ASSERT_GE(near_p.size(), 2u);
    for (const auto& q : near_p) EXPECT_EQ(q, near_p[0]);
}

// A T-junction inside ONE shape, through the cross-shape path: the vertex
// inserted on the long edge must take the T vertex's EXACT position, not an
// interpolation along the edge (the T vertex sits slightly off the line, so
// interpolating leaves a near-duplicate and a crack). DBridge raw NIF has 10
// near-duplicate positions; the pass was producing ~200 more.
TEST(NormalGenAcross, InsertedVertexSnapsToTheShapesOwnTVertex) {
    MeshCpu m;
    const glm::vec3 t{1.0f, 0.0004f, 0.0f};  // T vertex, slightly off the edge
    m.vertices = {at({0, 0, 0}), at({2, 0, 0}), at({1, -1, 0}),
                  at({0, 0, 0}), at(t), at({0.5f, 1, 0}),
                  at(t), at({2, 0, 0}), at({1.5f, 1, 0})};
    m.indices = {0, 2, 1, 3, 4, 5, 6, 7, 8};
    std::vector<NormalGenShape> shapes{{&m, glm::mat4(1.0f), {}}};
    generate_normals_across_shapes(shapes, 40.0f);
    for (const auto& v : m.vertices) {
        if (glm::length(v.position - t) < 1e-2f) EXPECT_EQ(v.position, t);
    }
}

// ── Spatial-grid equivalence ───────────────────────────────────────────────
// The repair finds candidate T points through a uniform grid (spec §3,
// "spatial-grid accelerated"). The grid is ONLY a candidate filter: the
// output must match the original brute-force scan exactly — same split points
// per edge, in the same order (the split picks the MIDDLE pending point, so
// order changes topology), same bits. The reference below is that original
// brute-force algorithm, kept verbatim apart from carrying only the channels
// this test compares (position, uv).
namespace {
using RefKey = std::array<std::uint32_t, 3>;

void brute_force_repair(MeshCpu& m) {
    std::vector<glm::vec3> points;
    {
        std::map<RefKey, bool> seen;
        for (const auto& v : m.vertices) {
            RefKey k;
            std::memcpy(k.data(), &v.position.x, sizeof(float) * 3);
            if (seen.try_emplace(k, true).second) points.push_back(v.position);
        }
    }
    auto points_inside = [&](const glm::vec3& a, const glm::vec3& b) {
        std::vector<glm::vec3> found;
        const glm::vec3 ab = b - a;
        const float len2 = glm::dot(ab, ab);
        if (len2 < 1e-12f) return found;
        const float tol = 1e-3f * std::sqrt(len2);
        for (const auto& p : points) {
            const float u = glm::dot(p - a, ab) / len2;
            if (u <= 1e-3f || u >= 1.0f - 1e-3f) continue;
            if (glm::length(p - a - u * ab) < tol) found.push_back(p);
        }
        return found;
    };
    auto param = [](const glm::vec3& a, const glm::vec3& b, const glm::vec3& p) {
        const glm::vec3 ab = b - a;
        return glm::dot(p - a, ab) / glm::dot(ab, ab);
    };
    auto insert = [&](std::uint32_t a, std::uint32_t b, float u, const glm::vec3& p) {
        const glm::vec3& pa = m.vertices[a].position;
        const glm::vec3& pb = m.vertices[b].position;
        if (std::lexicographical_compare(&pb.x, &pb.x + 3, &pa.x, &pa.x + 3)) {
            std::swap(a, b);
            u = param(m.vertices[a].position, m.vertices[b].position, p);
        }
        MeshCpu::Vertex v = m.vertices[a];
        v.uv = glm::mix(v.uv, m.vertices[b].uv, u);
        v.position = p;
        m.vertices.push_back(v);
        return static_cast<std::uint32_t>(m.vertices.size() - 1);
    };
    struct Work {
        std::array<std::uint32_t, 3> v;
        std::array<std::vector<glm::vec3>, 3> pts;
    };
    std::vector<std::uint32_t> out;
    for (std::size_t t = 0; t < m.indices.size() / 3; ++t) {
        Work first;
        first.v = {m.indices[t * 3], m.indices[t * 3 + 1], m.indices[t * 3 + 2]};
        for (int e = 0; e < 3; ++e)
            first.pts[e] = points_inside(m.vertices[first.v[e]].position,
                                         m.vertices[first.v[(e + 1) % 3]].position);
        std::vector<Work> work = {std::move(first)};
        while (!work.empty()) {
            Work w = std::move(work.back());
            work.pop_back();
            int k = -1;
            for (int e = 0; e < 3; ++e) if (!w.pts[e].empty()) { k = e; break; }
            if (k < 0) { out.insert(out.end(), w.v.begin(), w.v.end()); continue; }
            const std::uint32_t a = w.v[k], b = w.v[(k + 1) % 3], c = w.v[(k + 2) % 3];
            const glm::vec3 pa = m.vertices[a].position, pb = m.vertices[b].position;
            const glm::vec3 p = w.pts[k][w.pts[k].size() / 2];
            const float u = param(pa, pb, p);
            std::vector<glm::vec3> lo, hi;
            for (const auto& q : w.pts[k]) {
                if (q == p) continue;
                (param(pa, pb, q) < u ? lo : hi).push_back(q);
            }
            const std::uint32_t v = insert(a, b, u, p);
            work.push_back({{a, v, c}, {std::move(lo), {}, w.pts[(k + 2) % 3]}});
            work.push_back({{v, b, c}, {std::move(hi), w.pts[(k + 1) % 3], {}}});
        }
    }
    m.indices = std::move(out);
}

// A rotated, translated soup of coarse quads (n x n, unit cells) with a
// strip of fine quads (4 per unit) along the top AND the right side, so every
// fine vertex lies inside a coarse edge — several per edge, so the middle
// pick and the lo/hi partition order matter. Plus scattered small triangles
// (deterministic LCG) so the grid has occupied cells far from the strips.
MeshCpu many_t_junctions(int n) {
    const glm::mat4 xf = glm::rotate(glm::translate(glm::mat4(1.0f), {13.7f, -4.2f, 91.3f}),
                                     0.61f, glm::normalize(glm::vec3(0.3f, 1.0f, -0.7f)));
    MeshCpu m;
    auto quad = [&](float x0, float y0, float w, float h) {
        const glm::vec3 c[4] = {{x0, y0, 0}, {x0 + w, y0, 0}, {x0 + w, y0 + h, 0}, {x0, y0 + h, 0}};
        const auto base = static_cast<std::uint32_t>(m.vertices.size());
        for (const auto& p : c) {
            MeshCpu::Vertex v = at(glm::vec3(xf * glm::vec4(p, 1.0f)));
            v.uv = {p.x * 0.1f, p.y * 0.1f};
            m.vertices.push_back(v);
        }
        for (std::uint32_t i : {0u, 1u, 2u, 0u, 2u, 3u}) m.indices.push_back(base + i);
    };
    for (int y = 0; y < n; ++y)
        for (int x = 0; x < n; ++x) quad(float(x), float(y), 1, 1);
    for (int i = 0; i < n * 4; ++i) {
        quad(i * 0.25f, float(n), 0.25f, 0.5f);         // top strip
        quad(float(n), i * 0.25f, 0.5f, 0.25f);         // right strip
    }
    std::uint32_t s = 12345u;
    auto rnd = [&] { s = s * 1664525u + 1013904223u; return (s >> 8) / float(1u << 24); };
    for (int i = 0; i < 200; ++i) {
        const glm::vec3 o{rnd() * n, rnd() * n, 0.5f + rnd() * 3.0f};
        const auto base = static_cast<std::uint32_t>(m.vertices.size());
        for (int k = 0; k < 3; ++k)
            m.vertices.push_back(at(glm::vec3(xf * glm::vec4(
                o + glm::vec3(rnd(), rnd(), rnd()) * 0.3f, 1.0f))));
        for (std::uint32_t k : {0u, 1u, 2u}) m.indices.push_back(base + k);
    }
    return m;
}
}  // namespace

TEST(TJunctionRepair, GridAcceleratedRepairMatchesBruteForceExactly) {
    const int n = 12;
    MeshCpu got = many_t_junctions(n);
    MeshCpu want = got;
    const std::size_t verts_before = got.vertices.size();
    std::vector<glm::vec4> src;
    assets::detail::repair_t_junctions(got, src);
    brute_force_repair(want);

    // The mesh really exercises the repair: each of the 2n coarse strip-side
    // edges carries 3 fine T points (some per triangle twice, via the diagonal).
    ASSERT_GE(want.vertices.size() - verts_before, std::size_t(2 * n * 3));
    ASSERT_EQ(got.indices, want.indices);
    ASSERT_EQ(got.vertices.size(), want.vertices.size());
    for (std::size_t i = 0; i < want.vertices.size(); ++i) {
        ASSERT_EQ(got.vertices[i].position, want.vertices[i].position) << i;
        ASSERT_EQ(got.vertices[i].uv, want.vertices[i].uv) << i;
    }
    EXPECT_FALSE(any_vertex_inside_an_edge(got));
}
