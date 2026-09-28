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
