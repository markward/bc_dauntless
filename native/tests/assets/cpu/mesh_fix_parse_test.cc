// Tests for the mesh-fix file model, parser and FNV-1a content hash
// (spec: docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>

namespace {
const char* kValid = R"({
  "format": 1,
  "source": "data/Models/Ships/Galaxy/Galaxy.nif",
  "generator": "tools/gen_mesh_fixes.py",
  "merges": [{
    "patch":  {"block": 61, "name": "Ent-D Saucer Section:9"},
    "target": {"block": 14, "name": "Ent-D Saucer Section:1"},
    "method": "planar-mirrored",
    "max_fit_error": 7.1e-7,
    "uvs":    [[0.5, 0.25], [0.75, 1.0]],
    "weld":   [[0, 37], [1, 52]],
    "normals": null
  }]
})";
}  // namespace

TEST(MeshFixHash, Fnv1a64KnownVectors) {
    EXPECT_EQ(assets::fnv1a64_hex(""), "cbf29ce484222325");
    EXPECT_EQ(assets::fnv1a64_hex("a"), "af63dc4c8601ec8c");
    EXPECT_EQ(assets::fnv1a64_hex("foobar"), "85944171f73967e8");
}

TEST(MeshFixParse, ValidFileRoundTrips) {
    std::string err;
    auto fix = assets::parse_mesh_fix(kValid, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    ASSERT_EQ(fix->merges.size(), 1u);
    const auto& m = fix->merges[0];
    EXPECT_EQ(m.patch.block, 61u);
    EXPECT_EQ(m.patch.name, "Ent-D Saucer Section:9");
    EXPECT_EQ(m.target.block, 14u);
    ASSERT_EQ(m.uvs.size(), 2u);
    EXPECT_FLOAT_EQ(m.uvs[1][0], 0.75f);
    ASSERT_EQ(m.weld.size(), 2u);
    EXPECT_EQ(m.weld[1].first, 1u);
    EXPECT_EQ(m.weld[1].second, 52u);
    EXPECT_FALSE(m.normals.has_value());
}

TEST(MeshFixParse, NormalsArrayIsRead) {
    std::string text = kValid;
    text.replace(text.find("\"normals\": null"), 15,
                 "\"normals\": [[0,0,1],[0,1,0]]");
    std::string err;
    auto fix = assets::parse_mesh_fix(text, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    ASSERT_TRUE(fix->merges[0].normals.has_value());
    EXPECT_FLOAT_EQ((*fix->merges[0].normals)[1][1], 1.0f);
}

TEST(MeshFixParse, RejectsUnknownFormat) {
    std::string text = kValid;
    text.replace(text.find("\"format\": 1"), 11, "\"format\": 2");
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(text, &err).has_value());
    EXPECT_NE(err.find("format"), std::string::npos) << err;
}

TEST(MeshFixParse, RejectsMalformedJson) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix("{ not json", &err).has_value());
    EXPECT_FALSE(err.empty());
}

TEST(MeshFixParse, RejectsMissingFieldAndWrongShape) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(R"({"format":1})", &err).has_value());
    std::string bad_uv = kValid;
    bad_uv.replace(bad_uv.find("[0.5, 0.25]"), 11, "[0.5]");
    EXPECT_FALSE(assets::parse_mesh_fix(bad_uv, &err).has_value());
}

namespace {
constexpr const char* kGoldenB64 =
    "QlNEMQEABwAAAAQAAgABAAEAAQABAAEAAgAAAIA/AAAAQAAAQEAAAAAAgD4AAEA/AAAAPwAAAD8"
    "AAAAAzczMPc3MTD6amZk+zczMPgAAgD8AAAA/AACAPgAAgD8BAAAAAgAEAA==";
}

TEST(MeshFixShapeEditDecode, Base64RoundTripsKnownString) {
    auto d = assets::base64_decode("QlNEMQ==");
    ASSERT_TRUE(d.has_value());
    EXPECT_EQ(*d, "BSD1");
    EXPECT_FALSE(assets::base64_decode("Ql*EMQ==").has_value());
    EXPECT_FALSE(assets::base64_decode("QlNEM").has_value());   // bad length
}

TEST(MeshFixShapeEditDecode, DecodesGoldenPayload) {
    auto bytes = assets::base64_decode(kGoldenB64);
    ASSERT_TRUE(bytes.has_value());
    ASSERT_EQ(bytes->size(), 100u);
    std::string err;
    auto edits = assets::decode_shape_edits(*bytes, &err);
    ASSERT_TRUE(edits.has_value()) << err;
    ASSERT_EQ(edits->size(), 1u);
    const auto& e = (*edits)[0];
    EXPECT_EQ(e.block, 7u);
    EXPECT_EQ(e.orig_vertex_count, 4);
    EXPECT_EQ(e.orig_triangle_count, 2);
    ASSERT_EQ(e.moves.size(), 1u);
    EXPECT_EQ(e.moves[0].first, 2);
    EXPECT_FLOAT_EQ(e.moves[0].second.literal[2], 3.0f);
    ASSERT_EQ(e.uvs.size(), 1u);
    EXPECT_FLOAT_EQ(e.uvs[0].second.literal[1], 0.75f);
    ASSERT_EQ(e.add_vertices.size(), 1u);
    EXPECT_FLOAT_EQ(e.add_vertices[0].uv1[1], 0.4f);
    EXPECT_FLOAT_EQ(e.add_vertices[0].color[2], 0.25f);
    ASSERT_EQ(e.remove_triangles.size(), 1u);
    EXPECT_EQ(e.remove_triangles[0], 1);
    ASSERT_EQ(e.add_triangles.size(), 1u);
    EXPECT_EQ(e.add_triangles[0][2], 4);
}

TEST(MeshFixShapeEditDecode, RefusesBadMagicTruncationAndTrailingBytes) {
    auto good = *assets::base64_decode(kGoldenB64);
    std::string err;
    { auto b = good; b[0] = 'X';
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
    { auto b = good.substr(0, good.size() - 1);
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
    { auto b = good + "x";
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
}

namespace {
// BSD2 golden (spec §6.1): every record kind. Hand-assembled with struct and
// pinned byte-identical in tests/tools/test_shape_diff.py (GOLDEN_B64).
constexpr const char* kGoldenBsd2B64 =
    "QlNEMgEABwAAAAQAAgACAAIAAgABAAEAAQAAAACAPwAAAEAAAEBAAgABCQAAAAMAAAAAAACAPgAAQD8D"
    "AAEHAAAAAQAAAAAAPwAAAD8AAAAAAAAAAD4AAAA/AgABCQAAAAAAAQkAAAAAAAMAAQAAAAQABQA=";
}  // namespace

TEST(MeshFixShapeEditDecode, DecodesBsd2GoldenPayloadEveryRecordKind) {
    auto bytes = assets::base64_decode(kGoldenBsd2B64);
    ASSERT_TRUE(bytes.has_value());
    ASSERT_EQ(bytes->size(), 116u);
    std::string err;
    auto edits = assets::decode_shape_edits(*bytes, &err);
    ASSERT_TRUE(edits.has_value()) << err;
    ASSERT_EQ(edits->size(), 1u);
    const auto& e = (*edits)[0];
    EXPECT_EQ(e.block, 7u);
    EXPECT_EQ(e.orig_vertex_count, 4);
    EXPECT_EQ(e.orig_triangle_count, 2);
    ASSERT_EQ(e.moves.size(), 2u);
    EXPECT_EQ(e.moves[0].first, 1);
    EXPECT_FALSE(e.moves[0].second.ref.has_value());
    EXPECT_FLOAT_EQ(e.moves[0].second.literal[2], 3.0f);
    EXPECT_EQ(e.moves[1].first, 2);
    ASSERT_TRUE(e.moves[1].second.ref.has_value());
    EXPECT_EQ(e.moves[1].second.ref->block, 9u);
    EXPECT_EQ(e.moves[1].second.ref->vertex, 3);
    ASSERT_EQ(e.uvs.size(), 2u);
    EXPECT_FALSE(e.uvs[0].second.ref.has_value());
    EXPECT_FLOAT_EQ(e.uvs[0].second.literal[1], 0.75f);
    EXPECT_EQ(e.uvs[1].first, 3);
    ASSERT_TRUE(e.uvs[1].second.ref.has_value());
    EXPECT_EQ(e.uvs[1].second.ref->block, 7u);
    EXPECT_EQ(e.uvs[1].second.ref->vertex, 1);
    ASSERT_EQ(e.add_vertices.size(), 2u);
    const auto& a0 = e.add_vertices[0];
    EXPECT_FALSE(a0.pos.ref.has_value());
    EXPECT_FLOAT_EQ(a0.pos.literal[0], 0.5f);
    EXPECT_FALSE(a0.uv0.ref.has_value());
    EXPECT_FLOAT_EQ(a0.uv0.literal[0], 0.125f);
    ASSERT_TRUE(a0.attr_src.has_value());
    EXPECT_EQ(*a0.attr_src, 2);
    const auto& a1 = e.add_vertices[1];
    ASSERT_TRUE(a1.pos.ref.has_value());
    EXPECT_EQ(a1.pos.ref->block, 9u);
    EXPECT_EQ(a1.pos.ref->vertex, 0);
    ASSERT_TRUE(a1.uv0.ref.has_value());
    EXPECT_EQ(a1.uv0.ref->block, 9u);
    ASSERT_TRUE(a1.attr_src.has_value());
    EXPECT_EQ(*a1.attr_src, 3);
    ASSERT_EQ(e.remove_triangles.size(), 1u);
    EXPECT_EQ(e.remove_triangles[0], 1);
    ASSERT_EQ(e.add_triangles.size(), 1u);
    EXPECT_EQ(e.add_triangles[0], (std::array<std::uint16_t, 3>{0, 4, 5}));
}

TEST(MeshFixShapeEditDecode, Bsd1AddedVertexKeepsLiteralAttributesAndNoAttrSrc) {
    auto edits = assets::decode_shape_edits(*assets::base64_decode(kGoldenB64), nullptr);
    ASSERT_TRUE(edits.has_value());
    const auto& e = (*edits)[0];
    EXPECT_FALSE(e.moves[0].second.ref.has_value());
    EXPECT_FALSE(e.add_vertices[0].attr_src.has_value());
    EXPECT_FALSE(e.add_vertices[0].pos.ref.has_value());
}

TEST(MeshFixShapeEditDecode, Bsd2RefusesUnknownKindTruncationAndTrailingBytes) {
    const auto good = *assets::base64_decode(kGoldenBsd2B64);
    std::string err;
    // magic 4 + count 2 + block/counts 8 + five u16 counts 10 = 24; the first
    // move's u16 vertex, then its kind byte at offset 26.
    ASSERT_EQ(good[26], '\0');
    { auto b = good; b[26] = 2;
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value());
      EXPECT_NE(err.find("kind"), std::string::npos) << err; }
    { auto b = good.substr(0, good.size() - 1);
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
    { auto b = good + "x";
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
}

TEST(MeshFixShapeEditParse, ShapeEditsOnlyFileParses) {
    std::string text = std::string(R"({"format":1,"shape_edits":")") + kGoldenB64 + "\"}";
    std::string err;
    auto fix = assets::parse_mesh_fix(text, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    EXPECT_TRUE(fix->merges.empty());
    EXPECT_EQ(fix->shape_edits.size(), 1u);
}

TEST(MeshFixShapeEditParse, RefusesFileWithNeitherOp) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(R"({"format":1})", &err).has_value());
    EXPECT_FALSE(assets::parse_mesh_fix(
        R"({"format":1,"shape_edits":"!!!!"})", &err).has_value());
}
