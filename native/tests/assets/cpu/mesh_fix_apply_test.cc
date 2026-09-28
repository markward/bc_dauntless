// Tests for apply_mesh_fix: merge, weld and hide, all-or-nothing
// (spec: docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>
#include <cmath>

namespace {
// Root NiNode (id 1) with two NiTriShape children: target (id 2, data id 3)
// and patch (id 4, data id 5). The target is a unit quad at z=0 whose right
// edge x=1 is shared with the patch quad spanning x=1..2.
struct Synthetic {
    nif::File f;
    std::size_t target_idx = 1, patch_idx = 3;
};

nif::NiTriShapeData quad(float x0, float x1, float u0, float u1) {
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

Synthetic make() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4};
    nif::NiTriShape target; target.av.obj.name = "saucer"; target.data_link = 3;
    nif::NiTriShape patch;  patch.av.obj.name  = "id";     patch.data_link  = 5;
    s.f.blocks = {root, target, quad(0,1,0,0.5f), patch, quad(1,2,0,1)};
    s.f.block_ids = {1, 2, 3, 4, 5};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

assets::MeshFix fix_for(const Synthetic&) {
    assets::MeshFixMerge m;
    m.patch = {3, "id"}; m.target = {1, "saucer"};
    // Rebuilt UVs continue the target's u = x/2 mapping.
    m.uvs = {{0.5f,0},{1.0f,0},{1.0f,1},{0.5f,1}};
    m.weld = {{0,1},{3,2}};   // patch x=1 edge == target x=1 edge
    assets::MeshFix fix; fix.merges = {m};
    return fix;
}

const nif::NiTriShapeData& data(const Synthetic& s, std::size_t i) {
    return std::get<nif::NiTriShapeData>(s.f.blocks[i]);
}

// make() plus a second patch shape ("id2", block 5, data block 6) welded
// onto the SAME target ("saucer", block 1) as the first patch, for the
// shared-target-data refusal test.
Synthetic make_shared_target() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4, 6};
    nif::NiTriShape target; target.av.obj.name = "saucer"; target.data_link = 3;
    nif::NiTriShape patchA; patchA.av.obj.name = "id";  patchA.data_link = 5;
    nif::NiTriShape patchB; patchB.av.obj.name = "id2"; patchB.data_link = 7;
    s.f.blocks = {root, target, quad(0,1,0,0.5f), patchA, quad(1,2,0,1),
                  patchB, quad(2,3,0,1)};
    s.f.block_ids = {1, 2, 3, 4, 5, 6, 7};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

// Two entirely independent target/patch pairs (no shared data blocks), for
// the cross-merge-atomicity test: merge 0 is valid, merge 1 fails for an
// unrelated reason (name mismatch).
Synthetic make_two_independent() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4, 6, 8};
    nif::NiTriShape target1; target1.av.obj.name = "saucer1"; target1.data_link = 3;
    nif::NiTriShape patch1;  patch1.av.obj.name  = "id1";     patch1.data_link  = 5;
    nif::NiTriShape target2; target2.av.obj.name = "saucer2"; target2.data_link = 7;
    nif::NiTriShape patch2;  patch2.av.obj.name  = "id2";     patch2.data_link  = 9;
    s.f.blocks = {root, target1, quad(0,1,0,0.5f), patch1, quad(1,2,0,1),
                        target2, quad(10,11,0,0.5f), patch2, quad(11,12,0,1)};
    s.f.block_ids = {1, 2, 3, 4, 5, 6, 7, 8, 9};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}
}  // namespace

TEST(MeshFixApply, MergesWeldsAndHidesPatch) {
    auto s = make();
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_for(s)), "");
    const auto& t = data(s, 2);
    EXPECT_EQ(t.num_vertices, 6);             // 4 + 4 - 2 welded
    EXPECT_EQ(t.vertices.size(), 6u);
    EXPECT_EQ(t.normals.size(), 6u);
    EXPECT_EQ(t.uv_sets[0].size(), 6u);
    EXPECT_EQ(t.num_triangles, 4);
    EXPECT_EQ(t.num_triangle_points, 12u);
    EXPECT_EQ(t.num_match_groups, 0);
    EXPECT_TRUE(t.match_groups.empty());
    // Appended patch triangle {0,1,2} must reference the WELDED target vertex 1.
    EXPECT_EQ(t.triangles[2][0], 1);
    EXPECT_FLOAT_EQ(t.uv_sets[0][4].u, 1.0f);   // patch v1 (x=2) got u=1
    EXPECT_TRUE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, TransformsPatchIntoTargetFrame) {
    auto s = make();
    // Patch shape carries its own transform: data authored around the origin,
    // shape translated +1 in x. Same world placement as make()'s patch.
    auto& pd = std::get<nif::NiTriShapeData>(s.f.blocks[4]);
    for (auto& v : pd.vertices) v.x -= 1.0f;
    std::get<nif::NiTriShape>(s.f.blocks[3]).av.translation = {1, 0, 0};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_for(s)), "");
    const auto& t = data(s, 2);
    EXPECT_NEAR(t.vertices[4].x, 2.0f, 1e-6);    // patch v1 lands at world x=2
}

TEST(MeshFixApply, AppliesNormalOverride) {
    auto s = make();
    auto fix = fix_for(s);
    fix.merges[0].weld.clear();
    fix.merges[0].normals = std::vector<std::array<float,3>>(4, {0, 1, 0});
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_NEAR(data(s, 2).normals[5].y, 1.0f, 1e-6);
}

// Each refusal leaves the file untouched.
void expect_refused(assets::MeshFix fix, const char* why) {
    auto s = make();
    auto before = data(s, 2);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "") << why;
    EXPECT_EQ(data(s, 2).num_vertices, before.num_vertices) << why;
    EXPECT_EQ(data(s, 2).match_groups.size(), 1u) << why;
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u) << why;
}

TEST(MeshFixApply, RefusalsLeaveFileUntouched) {
    auto s = make();
    auto f = fix_for(s);
    { auto x = f; x.merges[0].patch.name = "other";      expect_refused(x, "name mismatch"); }
    { auto x = f; x.merges[0].patch.block = 99;          expect_refused(x, "block out of range"); }
    { auto x = f; x.merges[0].target.block = 0;          expect_refused(x, "not a trishape"); }
    { auto x = f; x.merges[0].uvs.pop_back();            expect_refused(x, "uv count"); }
    { auto x = f; x.merges[0].normals = std::vector<std::array<float,3>>(2, {0,0,1});
                                                         expect_refused(x, "normal count"); }
    { auto x = f; x.merges[0].weld.push_back({0, 2});    expect_refused(x, "patch vertex welded twice"); }
    { auto x = f; x.merges[0].weld = {{0, 9}};           expect_refused(x, "weld out of range"); }
    { auto x = f; x.merges[0].weld = {{0, 0}};           expect_refused(x, "weld positions differ"); }
    { auto x = f; x.merges[0].uvs[0] = {0.9f, 0};        expect_refused(x, "weld uv differs"); }
}

// Two merges welding onto the SAME target data block must be refused as a
// whole (a per-merge-only check would let both apply and corrupt the
// second merge's index remap — see fix-round-1 finding). Neither patch is
// hidden and the shared target is untouched.
TEST(MeshFixApply, RefusesWhenTwoMergesShareTargetData) {
    auto s = make_shared_target();
    auto fix = fix_for(s);
    assets::MeshFixMerge m2;
    m2.patch = {5, "id2"}; m2.target = {1, "saucer"};
    m2.uvs = {{0,0},{1,0},{1,1},{0,1}};
    fix.merges.push_back(m2);

    auto before = data(s, 2);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_EQ(data(s, 2).num_vertices, before.num_vertices);
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);  // patch A
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[5]).av.flags & 0x0001u);  // patch B
}

// Two fully independent merges: the first is valid, the second fails on an
// unrelated rule (name mismatch). The whole fix is still all-or-nothing —
// the first merge must NOT have applied.
TEST(MeshFixApply, SecondMergeFailureLeavesFirstUnapplied) {
    auto s = make_two_independent();
    assets::MeshFixMerge m1;
    m1.patch = {3, "id1"}; m1.target = {1, "saucer1"};
    m1.uvs = {{0,0},{1,0},{1,1},{0,1}};
    assets::MeshFixMerge m2;
    m2.patch = {7, "id2_typo"};  // wrong name -> rule 1 refusal
    m2.target = {5, "saucer2"};
    m2.uvs = {{0,0},{1,0},{1,1},{0,1}};
    assets::MeshFix fix; fix.merges = {m1, m2};

    auto before = data(s, 2);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_EQ(data(s, 2).num_vertices, before.num_vertices);
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesVertexOverflow) {
    auto s = make();
    auto& t = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    t.num_vertices = 65534;
    t.vertices.resize(65534, {5,5,5});
    t.normals.resize(65534, {0,0,1});
    t.uv_sets[0].resize(65534, {0,0});
    auto fix = fix_for(s);
    fix.merges[0].weld.clear();
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
}

// Phase-1 hardening: has_vertices / vertices.size() consistency, patch
// triangle indices in range, and a triangle-count overflow guard -- each a
// refusal, no mutation (final review, Ruling 9). Each mutates the FILE
// (not just the fix), so these build the fix from the already-mutated
// synthetic (mirroring RefusesVertexOverflow above) rather than going
// through expect_refused, which rebuilds its own untouched make().
TEST(MeshFixApply, RefusesWhenPatchHasNoVertexData) {
    auto s = make();
    auto& pd = std::get<nif::NiTriShapeData>(s.f.blocks[4]);
    pd.has_vertices = false;
    auto fix = fix_for(s);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesWhenTargetHasNoVertexData) {
    auto s = make();
    auto& td = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    td.has_vertices = false;
    auto fix = fix_for(s);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesWhenPatchVertexArraySizeMismatchesCount) {
    auto s = make();
    auto fix = fix_for(s);  // build the fix (uvs/weld) BEFORE truncating
    auto& pd = std::get<nif::NiTriShapeData>(s.f.blocks[4]);
    pd.vertices.pop_back();  // 3 vertices left, num_vertices still says 4
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesWhenTargetVertexArraySizeMismatchesCount) {
    auto s = make();
    auto fix = fix_for(s);
    auto& td = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    td.vertices.pop_back();
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesPatchTriangleIndexOutOfRange) {
    auto s = make();
    auto& pd = std::get<nif::NiTriShapeData>(s.f.blocks[4]);
    pd.triangles[0][0] = 99;  // patch only has 4 vertices (0..3)
    auto fix = fix_for(s);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, RefusesTriangleCountOverflow) {
    auto s = make();
    auto& t = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    t.num_triangles = 65534;  // + patch's 2 triangles > 65535
    auto fix = fix_for(s);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}
