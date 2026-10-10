// Tests for apply_mesh_fix's shape_edits op (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md §6-§7).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>

#include "support/content_root.h"

#include <filesystem>
#include <limits>

namespace {
// Root NiNode (id 1) with one NiTriShape (id 2, data id 3): a unit quad,
// no normals, vertex colours, two UV sets -- the DBridge shape profile.
struct Synthetic { nif::File f; };

nif::NiTriShapeData quad() {
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_uv = true;
    d.has_normals = false;
    d.vertices = {{0,0,0},{1,0,0},{1,1,0},{0,1,0}};
    d.has_vertex_colors = true;
    d.vertex_colors = {{1,1,1,1},{1,1,1,1},{1,1,1,1},{1,1,1,1}};
    d.uv_sets = {{{0,0},{1,0},{1,1},{0,1}}, {{0,0},{1,0},{1,1},{0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    d.num_match_groups = 1; d.match_groups = {{0,1}};
    return d;
}

Synthetic make() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2};
    nif::NiTriShape shape; shape.data_link = 3;
    s.f.blocks = {root, shape, quad()};
    s.f.block_ids = {1, 2, 3};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

const nif::NiTriShapeData& data(const Synthetic& s) {
    return std::get<nif::NiTriShapeData>(s.f.blocks[2]);
}

assets::ShapeEdit base_edit() {
    assets::ShapeEdit e;
    e.block = 1; e.orig_vertex_count = 4; e.orig_triangle_count = 2;
    return e;
}

assets::MeshFix fix_of(assets::ShapeEdit e) {
    assets::MeshFix f; f.shape_edits = {e}; return f;
}
}  // namespace

TEST(MeshFixShapeEdit, MoveOnlyChangesPositionsAndNothingElse) {
    auto s = make();
    auto e = base_edit();
    e.moves = {{2, {1.5f, 1.25f, 0.5f}}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    const auto& d = data(s);
    EXPECT_FLOAT_EQ(d.vertices[2].x, 1.5f);
    EXPECT_FLOAT_EQ(d.vertices[2].z, 0.5f);
    EXPECT_EQ(d.num_vertices, 4);
    EXPECT_EQ(d.num_triangles, 2);
    EXPECT_EQ(d.triangles[1][2], 3);
    EXPECT_FLOAT_EQ(d.uv_sets[0][2].u, 1.0f);
    EXPECT_FALSE(d.has_normals);
    EXPECT_TRUE(d.match_groups.empty());
    EXPECT_EQ(d.num_match_groups, 0);
}

TEST(MeshFixShapeEdit, AddsVerticesTrianglesAndRemovesInOrder) {
    auto s = make();
    auto e = base_edit();
    e.uvs = {{0, {0.25f, 0.75f}}};
    e.add_vertices = {{{0.5f, 0.5f, 1.0f}, {0.1f, 0.2f}, {0.3f, 0.4f}, {1.0f, 0.5f, 0.25f, 1.0f}}};
    e.remove_triangles = {0};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    const auto& d = data(s);
    EXPECT_EQ(d.num_vertices, 5);
    ASSERT_EQ(d.vertices.size(), 5u);
    ASSERT_EQ(d.uv_sets[0].size(), 5u);
    ASSERT_EQ(d.uv_sets[1].size(), 5u);
    ASSERT_EQ(d.vertex_colors.size(), 5u);
    EXPECT_FLOAT_EQ(d.uv_sets[0][0].u, 0.25f);
    EXPECT_FLOAT_EQ(d.uv_sets[1][4].v, 0.4f);
    EXPECT_FLOAT_EQ(d.vertex_colors[4].g, 0.5f);
    ASSERT_EQ(d.num_triangles, 2);
    EXPECT_EQ(d.num_triangle_points, 6u);
    EXPECT_EQ(d.triangles[0], (std::array<std::uint16_t, 3>{0, 2, 3}));   // survivor first
    EXPECT_EQ(d.triangles[1], (std::array<std::uint16_t, 3>{0, 1, 4}));   // then added
    EXPECT_NEAR(d.bound_center.z, 0.5f, 1e-6);                            // AABB z 0..1
}

TEST(MeshFixShapeEdit, NoColoursAndOneUvSetIgnoresThoseFields) {
    auto s = make();
    auto& d0 = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d0.has_vertex_colors = false; d0.vertex_colors.clear();
    d0.uv_sets.resize(1);
    auto e = base_edit();
    e.add_vertices = {{{0.5f, 0.5f, 1.0f}, {0.1f, 0.2f}, {0.3f, 0.4f}, {1, 1, 1, 1}}};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_TRUE(data(s).vertex_colors.empty());
    EXPECT_EQ(data(s).uv_sets.size(), 1u);
    EXPECT_EQ(data(s).uv_sets[0].size(), 5u);
}

namespace {
void expect_refused(assets::MeshFix fix, const char* why,
                    void (*mutate)(Synthetic&) = nullptr) {
    auto s = make();
    if (mutate) mutate(s);
    const auto before = data(s).vertices;
    const auto before_tris = data(s).triangles;
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "") << why;
    EXPECT_EQ(data(s).vertices.size(), before.size()) << why;
    EXPECT_FLOAT_EQ(data(s).vertices[2].x, before[2].x) << why;
    EXPECT_EQ(data(s).triangles, before_tris) << why;
    EXPECT_EQ(data(s).match_groups.size(), 1u) << why;
}
}  // namespace

TEST(MeshFixShapeEdit, RefusalsLeaveFileUntouched) {
    auto ok = base_edit();
    ok.moves = {{2, {9, 9, 9}}};
    { auto e = ok; e.block = 99;                   expect_refused(fix_of(e), "block out of range"); }
    { auto e = ok; e.block = 0;                    expect_refused(fix_of(e), "not a trishape"); }
    { auto e = ok; e.orig_vertex_count = 5;        expect_refused(fix_of(e), "vertex count mismatch"); }
    { auto e = ok; e.orig_triangle_count = 3;      expect_refused(fix_of(e), "triangle count mismatch"); }
    { auto e = ok; e.moves.push_back({4, {0,0,0}}); expect_refused(fix_of(e), "move out of range"); }
    { auto e = ok; e.uvs = {{7, {0,0}}};           expect_refused(fix_of(e), "uv out of range"); }
    { auto e = ok; e.remove_triangles = {2};       expect_refused(fix_of(e), "remove out of range"); }
    { auto e = ok; e.remove_triangles = {1, 1};    expect_refused(fix_of(e), "removed twice"); }
    { auto e = ok; e.add_triangles = {{0, 1, 4}};  expect_refused(fix_of(e), "add index out of range"); }
    { auto e = ok; e.add_triangles = {{0, 1, 1}};  expect_refused(fix_of(e), "repeated index"); }
    { auto e = base_edit();
      e.add_vertices = {{{2, 0, 0}, {0,0}, {0,0}, {1,1,1,1}}};
      e.add_triangles = {{0, 1, 4}};               expect_refused(fix_of(e), "zero area (collinear)"); }
    { auto f = fix_of(ok); f.shape_edits.push_back(ok);
                                                   expect_refused(f, "same block twice"); }
    expect_refused(fix_of(ok), "authored normals", [](Synthetic& s) {
        auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
        d.has_normals = true;
        d.normals.assign(4, {0, 0, 1});
    });
}

TEST(MeshFixShapeEdit, RefusesNonFiniteMovePosition) {
    auto ok = base_edit();
    ok.moves = {{2, {std::numeric_limits<float>::quiet_NaN(), 0, 0}}};
    expect_refused(fix_of(ok), "non-finite move position");
}

TEST(MeshFixShapeEdit, RefusesNonFiniteUvValue) {
    auto ok = base_edit();
    ok.uvs = {{0, {std::numeric_limits<float>::infinity(), 0}}};
    expect_refused(fix_of(ok), "non-finite uv value");
}

TEST(MeshFixShapeEdit, RefusesNonFiniteAddedVertexField) {
    auto ok = base_edit();
    ok.add_vertices = {{{std::numeric_limits<float>::quiet_NaN(), 0, 0}, {0,0}, {0,0}, {1,1,1,1}}};
    ok.add_triangles = {{0, 1, 4}};
    expect_refused(fix_of(ok), "non-finite added vertex field");
}

TEST(MeshFixShapeEdit, RefusesWhenUvSetSizeMismatchesVertexCount) {
    auto ok = base_edit();
    ok.moves = {{2, {9, 9, 9}}};
    expect_refused(fix_of(ok), "uv set size mismatch", [](Synthetic& s) {
        auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
        d.uv_sets[1].resize(3);   // was 4, now inconsistent with num_vertices
    });
}

TEST(MeshFixShapeEdit, RefusesWhenVertexColorSizeMismatchesVertexCount) {
    auto ok = base_edit();
    ok.moves = {{2, {9, 9, 9}}};
    expect_refused(fix_of(ok), "vertex color size mismatch", [](Synthetic& s) {
        auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
        d.vertex_colors.resize(3);   // was 4
    });
}

TEST(MeshFixShapeEdit, RefusesVertexOverflow) {
    auto s = make();
    auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d.num_vertices = 65535;
    d.vertices.resize(65535, {5, 5, 5});
    d.vertex_colors.resize(65535, {1, 1, 1, 1});
    d.uv_sets[0].resize(65535, {0, 0});
    d.uv_sets[1].resize(65535, {0, 0});
    auto e = base_edit();
    e.orig_vertex_count = 65535;
    e.add_vertices = {{{0, 0, 1}, {0,0}, {0,0}, {1,1,1,1}}};
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_EQ(data(s).vertices.size(), 65535u);
}

TEST(MeshFixShapeEdit, RefusesTriangleCountOverflow) {
    auto s = make();
    auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d.num_triangles = 65535;
    d.triangles.assign(65535, {0, 1, 2});
    d.num_triangle_points = 65535u * 3;
    auto e = base_edit();
    e.orig_triangle_count = 65535;
    e.add_triangles = {{0, 1, 3}};
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_EQ(data(s).triangles.size(), 65535u);
}

namespace {
// F5: a merge (target block-array idx1/data idx2, patch idx3/data idx4 --
// same layout as mesh_fix_apply_test.cc's make()) PLUS a third, independent
// shape (idx5/data idx6, DBridge-style: no normals) for a shape edit, so
// merge-vs-edit interaction can be tested without entangling the two ops'
// own validation rules.
struct MergeAndEditSynthetic { nif::File f; };

nif::NiTriShapeData merge_quad(float x0, float x1, float u0, float u1) {
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_normals = d.has_uv = true;
    d.vertices = {{x0,0,0},{x1,0,0},{x1,1,0},{x0,1,0}};
    d.normals  = {{0,0,1},{0,0,1},{0,0,1},{0,0,1}};
    d.uv_sets  = {{{u0,0},{u1,0},{u1,1},{u0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    d.num_match_groups = 1; d.match_groups = {{0,1}};
    return d;
}

MergeAndEditSynthetic make_merge_and_edit() {
    MergeAndEditSynthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4, 6};
    nif::NiTriShape target; target.av.obj.name = "saucer"; target.data_link = 3;
    nif::NiTriShape patch;  patch.av.obj.name  = "id";     patch.data_link  = 5;
    nif::NiTriShape third;  third.data_link = 7;    // the shape-edit subject
    s.f.blocks = {root, target, merge_quad(0,1,0,0.5f), patch, merge_quad(1,2,0,1),
                  third, quad()};
    s.f.block_ids = {1, 2, 3, 4, 5, 6, 7};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

assets::MeshFixMerge merge_for() {
    assets::MeshFixMerge m;
    m.patch = {3, "id"}; m.target = {1, "saucer"};
    m.uvs = {{0.5f,0},{1.0f,0},{1.0f,1},{0.5f,1}};
    m.weld = {{0,1},{3,2}};
    return m;
}
}  // namespace

TEST(MeshFixShapeEdit, RefusesMergeAndShapeEditOnTheSameDataBlock) {
    auto s = make_merge_and_edit();
    assets::MeshFix fix;
    fix.merges = {merge_for()};
    assets::ShapeEdit e;
    e.block = 1;                     // the merge's TARGET shape -- same data block
    e.orig_vertex_count = 4; e.orig_triangle_count = 2;
    e.moves = {{0, {9, 9, 9}}};
    fix.shape_edits = {e};

    const std::size_t before_count = std::get<nif::NiTriShapeData>(s.f.blocks[2]).vertices.size();
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    const auto& after = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    EXPECT_EQ(after.vertices.size(), before_count);
    EXPECT_FLOAT_EQ(after.vertices[0].x, 0.0f);   // target untouched by the (refused) merge or edit
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);  // patch not hidden
}

TEST(MeshFixShapeEdit, ValidMergePlusFailingShapeEditAppliesNeither) {
    auto s = make_merge_and_edit();
    assets::MeshFix fix;
    fix.merges = {merge_for()};
    assets::ShapeEdit e;
    e.block = 5;                     // the independent third shape
    e.orig_vertex_count = 5;         // wrong -- the real shape has 4 -- refused
    e.orig_triangle_count = 2;
    fix.shape_edits = {e};

    const std::size_t before_count = std::get<nif::NiTriShapeData>(s.f.blocks[2]).vertices.size();
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    const auto& after = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    EXPECT_EQ(after.vertices.size(), before_count);
    EXPECT_FLOAT_EQ(after.vertices[0].x, 0.0f);   // merge did NOT apply
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);  // patch not hidden
}

// --- BSD2 references and attr_src (spec §6.1, §6.2) ---

namespace {
assets::ShapeEditPos pos_ref(std::uint32_t block, std::uint16_t v) {
    assets::ShapeEditPos p; p.ref = assets::ShapeEditRef{block, v}; return p;
}
assets::ShapeEditUv uv_ref(std::uint32_t block, std::uint16_t v) {
    assets::ShapeEditUv u; u.ref = assets::ShapeEditRef{block, v}; return u;
}
assets::ShapeEditAddVertex added(assets::ShapeEditPos p, assets::ShapeEditUv uv,
                                 std::uint16_t attr_src) {
    assets::ShapeEditAddVertex a;
    a.pos = p; a.uv0 = uv; a.attr_src = attr_src;
    return a;
}

// Two shapes: A (block 1, data block 2 -- make()'s layout, so data() works)
// under the root, and B (block 4, data block 5) under node N (block 3),
// which is translated (10, 0, 0) and rotated +90 degrees about Z. B's colours
// and UV sets carry per-vertex values so a copy is traceable.
Synthetic make_two() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4};
    nif::NiTriShape a; a.data_link = 3;
    nif::NiNode n; n.child_links = {5};
    n.av.translation = {10, 0, 0};
    n.av.rotation = nif::Mat3x3{ .m = {0, -1, 0, 1, 0, 0, 0, 0, 1} };
    nif::NiTriShape b; b.data_link = 6;
    auto qb = quad();
    for (int i = 0; i < 4; ++i) {
        const float k = 0.1f * static_cast<float>(i + 1);
        qb.vertex_colors[i] = {k, k + 0.01f, k + 0.02f, 1.0f};
        qb.uv_sets[0][i] = {k, 0.5f};
        qb.uv_sets[1][i] = {0.5f, k};
    }
    s.f.blocks = {root, a, quad(), n, b, qb};
    s.f.block_ids = {1, 2, 3, 4, 5, 6};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

const nif::NiTriShapeData& data_b(const Synthetic& s) {
    return std::get<nif::NiTriShapeData>(s.f.blocks[5]);
}

assets::ShapeEdit edit_b() {
    assets::ShapeEdit e;
    e.block = 4; e.orig_vertex_count = 4; e.orig_triangle_count = 2;
    return e;
}
}  // namespace

TEST(MeshFixShapeEditRef, PositionRefTransformsTheSourceVertexIntoTheTargetFrame) {
    auto s = make_two();
    auto e = base_edit();                       // target A: identity frame
    e.moves = {{2, pos_ref(4, 1)}};             // B's (1,0,0) -> model (10,1,0)
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_NEAR(data(s).vertices[2].x, 10.0f, 1e-5);
    EXPECT_NEAR(data(s).vertices[2].y, 1.0f, 1e-5);
    EXPECT_NEAR(data(s).vertices[2].z, 0.0f, 1e-5);

    auto t = make_two();
    auto eb = edit_b();                         // target B: model (1,1,0) -> B-local (1,9,0)
    eb.moves = {{0, pos_ref(1, 2)}};
    ASSERT_EQ(assets::apply_mesh_fix(t.f, fix_of(eb)), "");
    EXPECT_NEAR(data_b(t).vertices[0].x, 1.0f, 1e-5);
    EXPECT_NEAR(data_b(t).vertices[0].y, 9.0f, 1e-5);
}

TEST(MeshFixShapeEditRef, RefIntoAShapeTheSameFixEditsReadsTheOriginalPosition) {
    auto s = make_two();
    auto eb = edit_b();
    eb.moves = {{1, {5.0f, 5.0f, 5.0f}}};       // applied first...
    auto ea = base_edit();
    ea.moves = {{2, pos_ref(4, 1)}};            // ...but A must see B's ORIGINAL vertex 1
    assets::MeshFix fix; fix.shape_edits = {eb, ea};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_NEAR(data(s).vertices[2].x, 10.0f, 1e-5);
    EXPECT_NEAR(data(s).vertices[2].y, 1.0f, 1e-5);
    EXPECT_FLOAT_EQ(data_b(s).vertices[1].x, 5.0f);
}

TEST(MeshFixShapeEditRef, SameShapeRefCopiesTheOriginalExactlyEvenIfItMoves) {
    auto s = make();
    auto e = base_edit();
    e.moves = {{0, {7.0f, 7.0f, 7.0f}}, {3, pos_ref(1, 0)}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_EQ(data(s).vertices[3].x, 0.0f);
    EXPECT_EQ(data(s).vertices[3].y, 0.0f);
    EXPECT_EQ(data(s).vertices[3].z, 0.0f);
    EXPECT_FLOAT_EQ(data(s).vertices[0].x, 7.0f);
}

TEST(MeshFixShapeEditRef, UvRefCopiesTheOriginalUv0EvenIfThatUvIsEdited) {
    auto s = make_two();
    auto e = base_edit();
    e.uvs = {{0, {0.9f, 0.9f}}, {1, uv_ref(1, 0)}, {2, uv_ref(4, 3)}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][0].u, 0.9f);
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][1].u, 0.0f);    // A's ORIGINAL uv 0
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][1].v, 0.0f);
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][2].u, 0.4f);    // B's uv 3
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][2].v, 0.5f);
}

TEST(MeshFixShapeEditRef, AddedVertexCopiesColourAndEveryExtraUvSetFromAttrSrc) {
    auto s = make_two();
    auto e = edit_b();
    e.add_vertices = {added(pos_ref(1, 2), uv_ref(4, 3), 2)};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    const auto& d = data_b(s);
    ASSERT_EQ(d.vertices.size(), 5u);
    EXPECT_NEAR(d.vertices[4].x, 1.0f, 1e-5);          // A's (1,1,0) in B's frame
    EXPECT_NEAR(d.vertices[4].y, 9.0f, 1e-5);
    EXPECT_FLOAT_EQ(d.uv_sets[0][4].u, 0.4f);          // uv0 by reference (B's 3)
    EXPECT_FLOAT_EQ(d.uv_sets[1][4].v, 0.3f);          // UV1 from attr_src 2
    EXPECT_FLOAT_EQ(d.vertex_colors[4].r, 0.3f);       // colour from attr_src 2
    EXPECT_FLOAT_EQ(d.vertex_colors[4].g, 0.31f);
    EXPECT_EQ(d.triangles.back(), (std::array<std::uint16_t, 3>{0, 1, 4}));
}

TEST(MeshFixShapeEditRef, LiteralAddedVertexWithAttrSrcOnAShapeWithoutColours) {
    auto s = make();
    auto& d0 = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d0.has_vertex_colors = false; d0.vertex_colors.clear();
    d0.uv_sets.resize(1);
    auto e = base_edit();
    assets::ShapeEditAddVertex a;
    a.pos.literal = {0.5f, 0.5f, 1.0f};
    a.uv0.literal = {0.25f, 0.5f};
    a.attr_src = 1;
    e.add_vertices = {a};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_TRUE(data(s).vertex_colors.empty());
    EXPECT_FLOAT_EQ(data(s).uv_sets[0][4].u, 0.25f);
    EXPECT_FLOAT_EQ(data(s).vertices[4].z, 1.0f);
}

namespace {
/// Like expect_refused, over make_two(): both shapes must be untouched.
void expect_refused_two(assets::MeshFix fix, const char* why,
                        void (*mutate)(Synthetic&) = nullptr) {
    auto s = make_two();
    if (mutate) mutate(s);
    const auto a_before = data(s).vertices;
    const auto b_before = data_b(s).vertices;
    const auto a_tris = data(s).triangles;
    const auto a_uv = data(s).uv_sets;
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "") << why;
    ASSERT_EQ(data(s).vertices.size(), a_before.size()) << why;
    ASSERT_EQ(data_b(s).vertices.size(), b_before.size()) << why;
    for (std::size_t i = 0; i < a_before.size(); ++i) {
        EXPECT_EQ(data(s).vertices[i].x, a_before[i].x) << why;
        EXPECT_EQ(data(s).vertices[i].y, a_before[i].y) << why;
    }
    for (std::size_t i = 0; i < b_before.size(); ++i)
        EXPECT_EQ(data_b(s).vertices[i].x, b_before[i].x) << why;
    EXPECT_EQ(data(s).triangles, a_tris) << why;
    EXPECT_EQ(data(s).uv_sets[0][1].u, a_uv[0][1].u) << why;
    EXPECT_EQ(data(s).match_groups.size(), 1u) << why;
}
}  // namespace

TEST(MeshFixShapeEditRef, EveryReferenceRefusalLeavesTheFileUntouched) {
    auto mv = [](assets::ShapeEditPos p) {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}, {2, p}}; return fix_of(e);
    };
    expect_refused_two(mv(pos_ref(99, 0)), "ref block out of range");
    expect_refused_two(mv(pos_ref(3, 0)), "ref block is a NiNode, not a NiTriShape");
    expect_refused_two(mv(pos_ref(2, 0)), "ref block is NiTriShapeData, not a NiTriShape");
    expect_refused_two(mv(pos_ref(4, 4)), "ref vertex == original count");
    expect_refused_two(mv(pos_ref(4, 0)), "ref shape's data unresolved", [](Synthetic& s) {
        std::get<nif::NiTriShape>(s.f.blocks[4]).data_link = 42;
    });
    {   // vertex 4 exists only AFTER the same fix grows B: still out of range
        auto eb = edit_b();
        eb.add_vertices = {added(pos_ref(4, 0), uv_ref(4, 0), 0)};
        auto ea = base_edit();
        ea.moves = {{2, pos_ref(4, 4)}};
        assets::MeshFix f; f.shape_edits = {eb, ea};
        expect_refused_two(f, "ref vertex valid only after the edit");
    }
    {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}};
        e.uvs = {{1, uv_ref(4, 9)}};
        expect_refused_two(fix_of(e), "uv ref vertex out of range");
    }
    {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}};
        e.uvs = {{1, uv_ref(0, 0)}};
        expect_refused_two(fix_of(e), "uv ref block is not a NiTriShape");
    }
    {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}};
        e.add_vertices = {added(pos_ref(1, 0), uv_ref(1, 0), 4)};
        e.add_triangles = {{1, 2, 4}};
        expect_refused_two(fix_of(e), "attr_src == original count");
    }
    {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}};
        assets::ShapeEditAddVertex a;
        a.pos.literal = {0.5f, 0.5f, std::numeric_limits<float>::infinity()};
        a.attr_src = 0;
        e.add_vertices = {a};
        expect_refused_two(fix_of(e), "non-finite literal added position");
    }
    {
        auto e = base_edit(); e.moves = {{0, {3, 3, 3}}};
        assets::ShapeEditUv u; u.literal = {std::numeric_limits<float>::quiet_NaN(), 0};
        e.uvs = {{1, u}};
        expect_refused_two(fix_of(e), "non-finite literal uv");
    }
}

// Real DBridge: block 11 sits in a translated frame, block 24 in a frame
// rotated 90 degrees about Z (and translated elsewhere). A reference from 11
// to a vertex of 24 must land on that vertex's MODEL-space position.
TEST(MeshFixShapeEditRef, RealDbridgeCrossFrameReferenceLandsOnTheReferencedVertex) {
    namespace fs = std::filesystem;
    const fs::path nif = test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF";
    if (!fs::exists(nif)) GTEST_SKIP() << "DBridge not installed";
    auto f = nif::load(nif);
    auto shape_data = [&](std::size_t block) -> nif::NiTriShapeData& {
        const auto link = std::get<nif::NiTriShape>(f.blocks.at(block)).data_link;
        for (std::size_t i = 0; i < f.block_ids.size(); ++i)
            if (f.block_ids[i] == link) return std::get<nif::NiTriShapeData>(f.blocks[i]);
        throw std::runtime_error("no data");
    };
    const auto& src = shape_data(24);
    const nif::Vec3 s3 = src.vertices.at(3), s5 = src.vertices.at(5);
    const nif::TexCoord uv5 = src.uv_sets.at(0).at(5);
    const glm::mat4 w11 = assets::nif_block_world(f, 11), w24 = assets::nif_block_world(f, 24);
    ASSERT_NE(w11, w24);
    auto& tgt = shape_data(11);
    const nif::Color4 c0 = tgt.vertex_colors.at(0);

    assets::ShapeEdit e;
    e.block = 11;
    e.orig_vertex_count = tgt.num_vertices;
    e.orig_triangle_count = tgt.num_triangles;
    e.moves = {{0, pos_ref(24, 3)}};
    e.add_vertices = {added(pos_ref(24, 5), uv_ref(24, 5), 0)};
    e.add_triangles = {{0, 1, tgt.num_vertices}};
    const std::uint16_t n = tgt.num_vertices;
    ASSERT_EQ(assets::apply_mesh_fix(f, fix_of(e)), "");

    auto model = [](const glm::mat4& w, const nif::Vec3& v) {
        return glm::vec3(w * glm::vec4(v.x, v.y, v.z, 1.0f));
    };
    const auto& d = shape_data(11);
    EXPECT_LT(glm::length(model(w11, d.vertices[0]) - model(w24, s3)), 1e-3f);
    EXPECT_LT(glm::length(model(w11, d.vertices[n]) - model(w24, s5)), 1e-3f);
    EXPECT_FLOAT_EQ(d.uv_sets[0][n].u, uv5.u);
    EXPECT_FLOAT_EQ(d.vertex_colors[n].r, c0.r);
}

TEST(MeshFixShapeEditRef, DeltaPositionIsTheReferencedOriginalPlusATargetLocalDelta) {
    auto s = make_two();
    auto e = base_edit();                       // target A (identity frame)
    assets::ShapeEditPos own = pos_ref(1, 2);   // A's own (1,1,0)...
    own.delta = {0.25f, -0.5f, 2.0f};           // ...plus a delta
    assets::ShapeEditPos far = pos_ref(4, 1);   // B's (1,0,0) -> A-local (10,1,0)
    far.delta = {0.0f, 0.0f, 1.0f};
    e.moves = {{2, own}, {3, far}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_FLOAT_EQ(data(s).vertices[2].x, 1.25f);
    EXPECT_FLOAT_EQ(data(s).vertices[2].y, 0.5f);
    EXPECT_FLOAT_EQ(data(s).vertices[2].z, 2.0f);
    EXPECT_NEAR(data(s).vertices[3].x, 10.0f, 1e-5);
    EXPECT_NEAR(data(s).vertices[3].z, 1.0f, 1e-5);

    auto t = make_two();
    auto eb = edit_b();                         // delta is in the TARGET's frame
    assets::ShapeEditPos d = pos_ref(4, 0);
    d.delta = {1.0f, 0.0f, 0.0f};
    eb.moves = {{0, d}};
    ASSERT_EQ(assets::apply_mesh_fix(t.f, fix_of(eb)), "");
    EXPECT_FLOAT_EQ(data_b(t).vertices[0].x, 1.0f);
    EXPECT_FLOAT_EQ(data_b(t).vertices[0].y, 0.0f);
}

TEST(MeshFixShapeEditRef, NonFiniteDeltaIsRefusedAndLeavesTheFileUntouched) {
    auto e = base_edit();
    assets::ShapeEditPos p = pos_ref(1, 0);
    p.delta = {0.0f, std::numeric_limits<float>::quiet_NaN(), 0.0f};
    e.moves = {{0, {3, 3, 3}}, {2, p}};
    expect_refused_two(fix_of(e), "non-finite delta");
}
