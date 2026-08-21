// Internal-header include path is added via target_include_directories
// pointing at native/src/assets/src.
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include "mesh_build.h"

TEST(MeshBuild, MinimalTriangle) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 3;
    data.has_vertices = true;
    data.vertices = {{0.0f, 0.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, {0.0f, 1.0f, 0.0f}};
    data.has_normals = true;
    data.normals = {{0, 0, 1}, {0, 0, 1}, {0, 0, 1}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.0f, 0.0f}, {1.0f, 0.0f}, {0.0f, 1.0f}});
    data.num_triangles = 1;
    data.num_triangle_points = 3;
    data.triangles.push_back({0, 1, 2});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, /*mat=*/0, /*node=*/2);
    EXPECT_EQ(mesh.vertices.size(), 3u);
    EXPECT_EQ(mesh.indices.size(), 3u);
    EXPECT_EQ(mesh.indices[0], 0u);
    EXPECT_EQ(mesh.indices[1], 1u);
    EXPECT_EQ(mesh.indices[2], 2u);
    EXPECT_EQ(mesh.material_index, 0);
    EXPECT_EQ(mesh.node_index, 2);
    EXPECT_FLOAT_EQ(mesh.vertices[1].position.x, 1.0f);
    EXPECT_EQ(mesh.vertices[0].color, glm::u8vec4(255, 255, 255, 255));
}

TEST(MeshBuild, VertexColorsAreCopied) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{0, 0, 0}};
    data.has_vertex_colors = true;
    data.vertex_colors = {{0.5f, 0.25f, 1.0f, 0.75f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.0f, 0.0f}});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_EQ(mesh.vertices[0].color.r, static_cast<std::uint8_t>(0.5f * 255 + 0.5f));
    EXPECT_EQ(mesh.vertices[0].color.a, static_cast<std::uint8_t>(0.75f * 255 + 0.5f));
}

TEST(MeshBuild, ExtraUvSetsArePreserved) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{0, 0, 0}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.1f, 0.2f}});  // primary
    data.uv_sets.push_back({{0.3f, 0.4f}});  // extra (detail map)

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_FLOAT_EQ(mesh.vertices[0].uv.x, 0.1f);
    ASSERT_EQ(mesh.extra_uvs.size(), 1u);
    EXPECT_FLOAT_EQ(mesh.extra_uvs[0][0].x, 0.3f);
}

TEST(MeshBuild, NoUvWhenAbsent) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 2;
    data.has_vertices = true;
    data.vertices = {{0, 0, 0}, {1, 0, 0}};
    data.has_uv = false;

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_FLOAT_EQ(mesh.vertices[0].uv.x, 0.0f);
    EXPECT_FLOAT_EQ(mesh.vertices[0].uv.y, 0.0f);
    EXPECT_TRUE(mesh.extra_uvs.empty());
}

// NiTriShape.av carries a local T/R/S that composes with the parent
// NiNode's world transform. We bake it into the vertex positions so
// the renderer sees node-local geometry. 366 of 549 ship-corpus
// NiTriShapes carry non-identity translation (e.g. Warbird's two
// halves at +/-470 along X); ignoring this collapses chunks to the
// node origin.
TEST(MeshBuild, BakesShapeTranslationIntoPositions) {
    nif::NiTriShape shape;
    shape.av.translation = {10.0f, 20.0f, 30.0f};
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{1.0f, 2.0f, 3.0f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.0f, 0.0f}});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.x, 11.0f);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.y, 22.0f);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.z, 33.0f);
}

TEST(MeshBuild, BakesShapeRotationIntoPositionsAndNormals) {
    // 90° rotation about +Z: x → y, y → -x, z → z.
    nif::NiTriShape shape;
    shape.av.rotation.m = {0, -1, 0,
                           1,  0, 0,
                           0,  0, 1};
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{1.0f, 0.0f, 0.0f}};
    data.has_normals = true;
    data.normals = {{1.0f, 0.0f, 0.0f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0, 0}});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_NEAR(mesh.vertices[0].position.x, 0.0f, 1e-6f);
    EXPECT_NEAR(mesh.vertices[0].position.y, 1.0f, 1e-6f);
    EXPECT_NEAR(mesh.vertices[0].position.z, 0.0f, 1e-6f);
    EXPECT_NEAR(mesh.vertices[0].normal.x, 0.0f, 1e-6f);
    EXPECT_NEAR(mesh.vertices[0].normal.y, 1.0f, 1e-6f);
    EXPECT_NEAR(mesh.vertices[0].normal.z, 0.0f, 1e-6f);
}

TEST(MeshBuild, BakesUniformScale) {
    nif::NiTriShape shape;
    shape.av.scale = 2.5f;
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{1.0f, 2.0f, -4.0f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0, 0}});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.x, 2.5f);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.y, 5.0f);
    EXPECT_FLOAT_EQ(mesh.vertices[0].position.z, -10.0f);
}

TEST(MeshBuild, ComposesTrsAsRotateScaleThenTranslate) {
    // Verify the composition order: position = R*(S*v) + T.
    nif::NiTriShape shape;
    shape.av.translation = {100.0f, 0.0f, 0.0f};
    shape.av.scale = 2.0f;
    // 90° about +Z, same as above.
    shape.av.rotation.m = {0, -1, 0,
                           1,  0, 0,
                           0,  0, 1};
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{1.0f, 0.0f, 0.0f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0, 0}});

    // v scaled to (2, 0, 0); rotated to (0, 2, 0); translated to (100, 2, 0).
    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_NEAR(mesh.vertices[0].position.x, 100.0f, 1e-5f);
    EXPECT_NEAR(mesh.vertices[0].position.y, 2.0f, 1e-5f);
    EXPECT_NEAR(mesh.vertices[0].position.z, 0.0f, 1e-5f);
}
