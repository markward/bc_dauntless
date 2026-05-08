// native/tests/nif/ni_tri_shape_test.cc — synthetic unit tests for the
// NiTriShape and NiTriShapeData parsers. End-to-end testing on real BC
// files requires the property-block parsers (Tasks 23-24) so the walker
// can progress past the first NiZBufferProperty.
#include <gtest/gtest.h>

#include <nif/block.h>
#include <nif/error.h>

#include "../../src/nif/src/dispatch.h"
#include "../../src/nif/src/reader.h"

#include <cstdint>
#include <cstring>
#include <variant>
#include <vector>

namespace {

// Pack helpers — append little-endian primitives to a buffer.
void put_u16(std::vector<unsigned char>& v, std::uint16_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
}
void put_u32(std::vector<unsigned char>& v, std::uint32_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
    v.push_back((x >> 16) & 0xFF);
    v.push_back((x >> 24) & 0xFF);
}
void put_f32(std::vector<unsigned char>& v, float x) {
    std::uint32_t u;
    std::memcpy(&u, &x, 4);
    put_u32(v, u);
}
void put_str_u32(std::vector<unsigned char>& v, const std::string& s) {
    put_u32(v, static_cast<std::uint32_t>(s.size()));
    for (char c : s) v.push_back(static_cast<unsigned char>(c));
}

void put_av_object_base_minimal(std::vector<unsigned char>& v,
                                const std::string& name) {
    put_str_u32(v, name);
    put_u32(v, 0);                    // extra_data_link
    put_u32(v, 0);                    // controller_link
    put_u16(v, 0x000c);               // flags
    for (int i = 0; i < 3; ++i) put_f32(v, 0.0f);   // translation
    for (int i = 0; i < 9; ++i) {                   // rotation = identity
        put_f32(v, (i == 0 || i == 4 || i == 8) ? 1.0f : 0.0f);
    }
    put_f32(v, 1.0f);                                // scale
    for (int i = 0; i < 3; ++i) put_f32(v, 0.0f);    // velocity
    put_u32(v, 0);                                   // num_properties
    put_u32(v, 0);                                   // has_bounding_volume = false
}

}  // namespace

TEST(NiTriShape, ParsesAvBaseAndDataLink) {
    std::vector<unsigned char> bytes;
    put_av_object_base_minimal(bytes, "MyShape");
    put_u32(bytes, /*data_link=*/0xDEADBEEF);

    nif::Reader r(bytes.data(), bytes.size(), "<test>");
    nif::Block block = nif::Dispatch::instance().get("NiTriShape")(r);
    auto* shape = std::get_if<nif::NiTriShape>(&block);
    ASSERT_NE(shape, nullptr);
    EXPECT_EQ(shape->av.name, "MyShape");
    EXPECT_EQ(shape->data_link, 0xDEADBEEFu);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}

TEST(NiTriShapeData, ParsesEmptyMesh) {
    // 0 vertices, no normals, bound_center=(0,0,0), bound_radius=0,
    // no vertex colors, data_flags=1 (one UV set), has_uv=false,
    // 0 triangles, 0 match groups.
    std::vector<unsigned char> bytes;
    put_u16(bytes, 0);              // num_vertices
    put_u32(bytes, 0);              // has_vertices = false
    put_u32(bytes, 0);              // has_normals = false
    for (int i = 0; i < 3; ++i) put_f32(bytes, 0.0f);  // bound_center
    put_f32(bytes, 0.0f);            // bound_radius
    put_u32(bytes, 0);              // has_vertex_colors = false
    put_u16(bytes, 1);              // data_flags = 1 UV set
    put_u32(bytes, 0);              // has_uv = false
    put_u16(bytes, 0);              // num_triangles
    put_u32(bytes, 0);              // num_triangle_points
    put_u16(bytes, 0);              // num_match_groups

    nif::Reader r(bytes.data(), bytes.size(), "<test>");
    nif::Block block = nif::Dispatch::instance().get("NiTriShapeData")(r);
    auto* data = std::get_if<nif::NiTriShapeData>(&block);
    ASSERT_NE(data, nullptr);
    EXPECT_EQ(data->num_vertices, 0);
    EXPECT_FALSE(data->has_vertices);
    EXPECT_FALSE(data->has_normals);
    EXPECT_EQ(data->num_triangles, 0);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}

TEST(NiTriShapeData, ParsesSingleTriangleWithNormalsAndOneUVSet) {
    // 3 vertices forming one triangle, with normals and one UV set.
    std::vector<unsigned char> bytes;
    put_u16(bytes, 3);              // num_vertices
    put_u32(bytes, 1);              // has_vertices
    // 3 vertices
    put_f32(bytes, 0.0f); put_f32(bytes, 0.0f); put_f32(bytes, 0.0f);
    put_f32(bytes, 1.0f); put_f32(bytes, 0.0f); put_f32(bytes, 0.0f);
    put_f32(bytes, 0.0f); put_f32(bytes, 1.0f); put_f32(bytes, 0.0f);
    put_u32(bytes, 1);              // has_normals
    // 3 normals (all +Z)
    for (int i = 0; i < 3; ++i) {
        put_f32(bytes, 0.0f); put_f32(bytes, 0.0f); put_f32(bytes, 1.0f);
    }
    // bound_center, bound_radius
    put_f32(bytes, 0.5f); put_f32(bytes, 0.5f); put_f32(bytes, 0.0f);
    put_f32(bytes, 0.7071f);
    put_u32(bytes, 0);              // has_vertex_colors
    put_u16(bytes, 1);              // data_flags = 1 UV set
    put_u32(bytes, 1);              // has_uv = true
    // 3 UV coords for the single set
    put_f32(bytes, 0.0f); put_f32(bytes, 0.0f);
    put_f32(bytes, 1.0f); put_f32(bytes, 0.0f);
    put_f32(bytes, 0.0f); put_f32(bytes, 1.0f);
    put_u16(bytes, 1);              // num_triangles
    put_u32(bytes, 3);              // num_triangle_points
    // one triangle (0, 1, 2)
    put_u16(bytes, 0); put_u16(bytes, 1); put_u16(bytes, 2);
    put_u16(bytes, 0);              // num_match_groups

    nif::Reader r(bytes.data(), bytes.size(), "<test>");
    nif::Block block = nif::Dispatch::instance().get("NiTriShapeData")(r);
    auto* data = std::get_if<nif::NiTriShapeData>(&block);
    ASSERT_NE(data, nullptr);
    EXPECT_EQ(data->num_vertices, 3);
    ASSERT_EQ(data->vertices.size(), 3u);
    EXPECT_FLOAT_EQ(data->vertices[1].x, 1.0f);
    EXPECT_FLOAT_EQ(data->vertices[2].y, 1.0f);
    ASSERT_EQ(data->normals.size(), 3u);
    EXPECT_FLOAT_EQ(data->normals[0].z, 1.0f);
    ASSERT_EQ(data->uv_sets.size(), 1u);
    ASSERT_EQ(data->uv_sets[0].size(), 3u);
    EXPECT_FLOAT_EQ(data->uv_sets[0][1].u, 1.0f);
    EXPECT_FLOAT_EQ(data->uv_sets[0][2].v, 1.0f);
    ASSERT_EQ(data->triangles.size(), 1u);
    EXPECT_EQ(data->triangles[0][0], 0);
    EXPECT_EQ(data->triangles[0][1], 1);
    EXPECT_EQ(data->triangles[0][2], 2);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}
