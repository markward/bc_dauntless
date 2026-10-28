// Tests for the BSM1 smoothing records of a mesh fix (spec:
// docs/superpowers/specs/2026-10-27-bridge-authored-smoothing-design.md §3.2).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>

#include <string>

namespace {
// Same synthetic file as mesh_fix_shape_edit_test.cc: root NiNode, one
// NiTriShape (block 1) over a 4-vertex quad (block 2), no normals.
nif::File make() {
    nif::File f;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2};
    nif::NiTriShape shape; shape.data_link = 3;
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_uv = true;
    d.vertices = {{0,0,0},{1,0,0},{1,1,0},{0,1,0}};
    d.uv_sets = {{{0,0},{1,0},{1,1},{0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    f.blocks = {root, shape, d};
    f.block_ids = {1, 2, 3};
    f.root = nif::BlockHandle{&f.blocks.front()};
    return f;
}

const nif::NiTriShapeData& data(const nif::File& f) {
    return std::get<nif::NiTriShapeData>(f.blocks[2]);
}

assets::MeshFixSmoothing rec(std::uint16_t n = 4) {
    assets::MeshFixSmoothing s;
    s.block = 1; s.vertex_count = n;
    s.edges.hard = {{0, 1}};
    s.edges.soft = {{0, 2}, {1, 2}};
    return s;
}

assets::MeshFix fix_of(assets::MeshFixSmoothing s) {
    assets::MeshFix f; f.smoothing = {s}; return f;
}

void expect_refused(const assets::MeshFix& fix, const char* why) {
    auto f = make();
    EXPECT_NE(assets::apply_mesh_fix(f, fix), "") << why;
    EXPECT_FALSE(data(f).authored_edges.has_value()) << why;
    EXPECT_EQ(data(f).vertices.size(), 4u) << why;
}

const char* kGolden = "QlNNMQIABwAAAAQAAQACAAAAAQAAAAIAAQACAAwAAAADAAAAAAA=";
}  // namespace

TEST(MeshFixSmoothing, DecodesTheGoldenBlob) {
    auto bytes = assets::base64_decode(kGolden);
    ASSERT_TRUE(bytes);
    std::string err;
    auto r = assets::decode_smoothing(*bytes, &err);
    ASSERT_TRUE(r) << err;
    ASSERT_EQ(r->size(), 2u);
    EXPECT_EQ((*r)[0].block, 7u);
    EXPECT_EQ((*r)[0].vertex_count, 4);
    ASSERT_EQ((*r)[0].edges.hard.size(), 1u);
    EXPECT_EQ((*r)[0].edges.hard[0], (std::array<std::uint16_t, 2>{0, 1}));
    ASSERT_EQ((*r)[0].edges.soft.size(), 2u);
    EXPECT_EQ((*r)[0].edges.soft[0], (std::array<std::uint16_t, 2>{0, 2}));
    EXPECT_EQ((*r)[0].edges.soft[1], (std::array<std::uint16_t, 2>{1, 2}));
    EXPECT_EQ((*r)[1].block, 12u);
    EXPECT_EQ((*r)[1].vertex_count, 3);
    EXPECT_TRUE((*r)[1].edges.hard.empty());
    EXPECT_TRUE((*r)[1].edges.soft.empty());
}

TEST(MeshFixSmoothing, DecodeRefusesBadMagicTruncationTrailingBytes) {
    const std::string good = *assets::base64_decode(kGolden);
    std::string err;
    std::string bad = good; bad[0] = 'X';
    EXPECT_FALSE(assets::decode_smoothing(bad, &err));
    EXPECT_FALSE(err.empty());
    err.clear();
    EXPECT_FALSE(assets::decode_smoothing(good.substr(0, good.size() - 1), &err));
    EXPECT_FALSE(err.empty());
    err.clear();
    EXPECT_FALSE(assets::decode_smoothing(good + "x", &err));
    EXPECT_FALSE(err.empty());
    err.clear();
    EXPECT_FALSE(assets::decode_smoothing("BS", &err));
    EXPECT_FALSE(err.empty());
}

TEST(MeshFixSmoothing, ParseAcceptsASmoothingOnlyFix) {
    std::string err;
    auto fix = assets::parse_mesh_fix(
        std::string("{\"format\": 1, \"smoothing\": \"") + kGolden + "\"}", &err);
    ASSERT_TRUE(fix) << err;
    EXPECT_EQ(fix->smoothing.size(), 2u);
    EXPECT_TRUE(fix->merges.empty());
}

TEST(MeshFixSmoothing, AttachesEdges) {
    auto f = make();
    ASSERT_EQ(assets::apply_mesh_fix(f, fix_of(rec())), "");
    ASSERT_TRUE(data(f).authored_edges.has_value());
    EXPECT_EQ(data(f).authored_edges->hard.size(), 1u);
    EXPECT_EQ(data(f).authored_edges->soft.size(), 2u);
}

TEST(MeshFixSmoothing, AttachesEdgesAfterShapeEdits) {
    auto f = make();
    assets::ShapeEdit e;
    e.block = 1; e.orig_vertex_count = 4; e.orig_triangle_count = 2;
    e.add_vertices = {{{0.5f, 0.5f, 1.0f}, {0.1f, 0.2f}, {0, 0}, {1, 1, 1, 1}}};
    e.add_triangles = {{0, 1, 4}};
    auto s = rec(5);
    s.edges.soft.push_back({3, 4});
    assets::MeshFix fix; fix.shape_edits = {e}; fix.smoothing = {s};
    ASSERT_EQ(assets::apply_mesh_fix(f, fix), "");
    EXPECT_EQ(data(f).num_vertices, 5);
    ASSERT_TRUE(data(f).authored_edges.has_value());
    EXPECT_EQ(data(f).authored_edges->soft.back(), (std::array<std::uint16_t, 2>{3, 4}));
}

TEST(MeshFixSmoothing, RefusalsLeaveFileUntouched) {
    { auto s = rec(); s.block = 99;                expect_refused(fix_of(s), "block out of range"); }
    { auto s = rec(); s.block = 0;                 expect_refused(fix_of(s), "not a trishape"); }
    { auto s = rec(5);                             expect_refused(fix_of(s), "count != final count"); }
    { auto s = rec(); s.edges.soft = {{0, 4}};     expect_refused(fix_of(s), "index >= count"); }
    { auto s = rec(); s.edges.hard = {{2, 1}};     expect_refused(fix_of(s), "a >= b"); }
    { auto s = rec(); s.edges.hard = {{1, 1}};     expect_refused(fix_of(s), "a == b"); }
    { auto s = rec(); s.edges.soft = {{1, 2}, {0, 2}}; expect_refused(fix_of(s), "not ascending"); }
    { auto s = rec(); s.edges.soft = {{0, 2}, {0, 2}}; expect_refused(fix_of(s), "duplicate"); }
    { auto s = rec(); s.edges.soft = {{0, 1}};     expect_refused(fix_of(s), "in both lists"); }
    {
        assets::MeshFix fix; fix.smoothing = {rec(), rec()};
        expect_refused(fix, "block listed twice");
    }
    {
        auto f = make();
        std::get<nif::NiTriShapeData>(f.blocks[2]).has_normals = true;
        EXPECT_NE(assets::apply_mesh_fix(f, fix_of(rec())), "") << "authored normals";
        EXPECT_FALSE(data(f).authored_edges.has_value());
    }
}

TEST(MeshFixSmoothing, ParseRefusesBadBase64AndNonStringSmoothing) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix("{\"format\": 1, \"smoothing\": \"!!!!\"}", &err));
    EXPECT_FALSE(err.empty());
    err.clear();
    EXPECT_FALSE(assets::parse_mesh_fix("{\"format\": 1, \"smoothing\": 5}", &err));
    EXPECT_FALSE(err.empty());
}

namespace {
// Two normal-bearing shapes: block 1 (merge target "t"), block 3 (patch "p").
nif::File make_merge_file() {
    auto f = make();
    std::get<nif::NiTriShapeData>(f.blocks[2]).has_normals = true;
    std::get<nif::NiTriShapeData>(f.blocks[2]).normals = {{0,0,1},{0,0,1},{0,0,1},{0,0,1}};
    std::get<nif::NiTriShape>(f.blocks[1]).av.obj.name = "t";
    nif::NiTriShape patch; patch.data_link = 5; patch.av.obj.name = "p";
    nif::NiTriShapeData pd;
    pd.num_vertices = 3; pd.has_vertices = pd.has_uv = true; pd.has_normals = true;
    pd.vertices = {{0,0,0},{1,0,0},{1,1,0}};
    pd.normals = {{0,0,1},{0,0,1},{0,0,1}};
    pd.uv_sets = {{{0,0},{1,0},{1,1}}};
    pd.num_triangles = 1; pd.num_triangle_points = 3; pd.triangles = {{0,1,2}};
    std::get<nif::NiNode>(f.blocks[0]).child_links = {2, 4};
    f.blocks.push_back(patch); f.blocks.push_back(pd);
    f.block_ids.push_back(4); f.block_ids.push_back(5);
    f.root = nif::BlockHandle{&f.blocks.front()};
    return f;
}
}  // namespace

TEST(MeshFixSmoothing, RefusesAShapeWhoseDataAMergeUses) {
    auto f = make_merge_file();
    assets::MeshFixMerge m;
    m.patch = {3, "p"}; m.target = {1, "t"};
    m.uvs = {{0,0},{1,0},{1,1}};
    m.weld = {{0, 0}};
    assets::MeshFix fix; fix.merges = {m};
    auto control = make_merge_file();
    ASSERT_EQ(assets::apply_mesh_fix(control, fix), "");   // merge is valid alone

    fix.smoothing = {rec()};
    const std::string err = assets::apply_mesh_fix(f, fix);
    EXPECT_NE(err.find("used by merge"), std::string::npos) << err;
    EXPECT_FALSE(data(f).authored_edges.has_value());
}

namespace {
// make() plus a second NiTriShape (block 4) over the SAME data block.
nif::File make_shared_data_file() {
    auto f = make();
    nif::NiTriShape twin; twin.data_link = 3; twin.av.obj.name = "twin";
    std::get<nif::NiNode>(f.blocks[0]).child_links = {2, 4};
    f.blocks.push_back(twin);
    f.block_ids.push_back(4);
    f.root = nif::BlockHandle{&f.blocks.front()};
    return f;
}
}  // namespace

TEST(MeshFixSmoothing, RefusesADataBlockSharedWithAnotherShape) {
    auto f = make_shared_data_file();
    const std::string err = assets::apply_mesh_fix(f, fix_of(rec()));
    EXPECT_NE(err.find("shared"), std::string::npos) << err;
    EXPECT_FALSE(data(f).authored_edges.has_value());
}

TEST(MeshFixSmoothing, RefusesTwoRecordsOnOneDataBlock) {
    auto f = make_shared_data_file();
    auto second = rec();
    second.block = 4;
    assets::MeshFix fix; fix.smoothing = {rec(), second};
    EXPECT_NE(assets::apply_mesh_fix(f, fix), "");
    EXPECT_FALSE(data(f).authored_edges.has_value());
}
