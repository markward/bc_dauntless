// Tests for apply_mesh_fix's shape_edits op (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md §6-§7).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>
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
