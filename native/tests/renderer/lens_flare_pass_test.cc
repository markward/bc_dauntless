// native/tests/renderer/lens_flare_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/lens_flare_pass.h>

#include <cmath>

using renderer::build_ngon_mesh;
using renderer::NgonVertex;

TEST(LensFlareMesh, EightWedgesHas24Vertices) {
    auto mesh = build_ngon_mesh(8);
    EXPECT_EQ(mesh.vertices.size(), 24u);   // 3 verts per wedge, 8 wedges
    EXPECT_EQ(mesh.indices.size(), 24u);    // 3 indices per wedge, 8 wedges
}

TEST(LensFlareMesh, CenterVertexUvIsTopMiddle) {
    auto mesh = build_ngon_mesh(8);
    for (std::size_t k = 0; k < 8; ++k) {
        const auto& v = mesh.vertices[k * 3 + 0];
        EXPECT_FLOAT_EQ(v.pos[0], 0.0f);
        EXPECT_FLOAT_EQ(v.pos[1], 0.0f);
        EXPECT_FLOAT_EQ(v.uv[0],  0.5f);
        EXPECT_FLOAT_EQ(v.uv[1],  1.0f);
    }
}

TEST(LensFlareMesh, OuterVertexUvsAreCornerBottoms) {
    auto mesh = build_ngon_mesh(8);
    for (std::size_t k = 0; k < 8; ++k) {
        const auto& left  = mesh.vertices[k * 3 + 1];
        const auto& right = mesh.vertices[k * 3 + 2];
        EXPECT_FLOAT_EQ(left.uv[0],  0.0f);
        EXPECT_FLOAT_EQ(left.uv[1],  0.0f);
        EXPECT_FLOAT_EQ(right.uv[0], 1.0f);
        EXPECT_FLOAT_EQ(right.uv[1], 0.0f);
    }
}

TEST(LensFlareMesh, OuterVerticesAreOnUnitCircle) {
    auto mesh = build_ngon_mesh(30);
    for (std::size_t k = 0; k < 30; ++k) {
        const auto& left  = mesh.vertices[k * 3 + 1];
        const auto& right = mesh.vertices[k * 3 + 2];
        const float lr = std::sqrt(left.pos[0]  * left.pos[0]  + left.pos[1]  * left.pos[1]);
        const float rr = std::sqrt(right.pos[0] * right.pos[0] + right.pos[1] * right.pos[1]);
        EXPECT_NEAR(lr, 1.0f, 1e-5f);
        EXPECT_NEAR(rr, 1.0f, 1e-5f);
    }
}

TEST(LensFlareMesh, IndicesAreSequential) {
    auto mesh = build_ngon_mesh(6);
    for (std::size_t i = 0; i < mesh.indices.size(); ++i) {
        EXPECT_EQ(mesh.indices[i], static_cast<unsigned int>(i));
    }
}
