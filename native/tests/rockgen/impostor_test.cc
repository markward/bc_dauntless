#include <gtest/gtest.h>
#include <assets/mesh.h>
#include <rockgen/impostor.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>
#include <rockgen/surface.h>

#include "mini_recipe.h"

#include <glm/glm.hpp>

#include <cstdint>

TEST(Impostor, SixteenFixedViews) {
    auto d = rockgen::impostor_view_dirs();
    ASSERT_EQ(d.size(), 16u);
    for (auto& v : d) EXPECT_NEAR(glm::length(v), 1.0f, 1e-5f);
    EXPECT_EQ(d, rockgen::impostor_view_dirs());
}

TEST(Impostor, CoverageInEveryCell) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    auto surf = rockgen::generate_rock_surface(s[0]);
    auto imp = rockgen::bake_impostor(lods[1], surf, 32);
    ASSERT_EQ(imp.albedo.width, 128u);
    for (int cell = 0; cell < 16; ++cell) {
        int cx = (cell % 4) * 32 + 16, cy = (cell / 4) * 32 + 16;   // cell centre is on the rock
        EXPECT_GT(imp.albedo.pixels[(cy * 128 + cx) * 4 + 3], 0) << cell;
        EXPECT_EQ(imp.albedo.pixels[((cell / 4) * 32 * 128 + (cell % 4) * 32) * 4 + 3], 0) << cell; // corner empty
    }
}

// A flat, origin-centred rectangle (world y=0 plane) split into two
// triangles along the diagonal through two ANTIPODAL corners (C11 == -C00).
// That diagonal's midpoint is exactly the origin, and bake_impostor's screen
// mapping sends the origin to exactly the view's centre ((0+he)/(2he) == 0.5
// for ANY half-extent `he`, since dot(0, axis) == 0 for every axis) -- so
// for an ODD view_size the shared edge passes through the EXACT centre of
// the centre pixel, regardless of which of the 16 fixed view directions
// projects it. This needs no knowledge of the view's specific basis vectors:
// a rounding-induced "both triangles reject this pixel" crack along that
// edge would show up as a hole at (and immediately around) the centre pixel
// of view 0's cell.
TEST(Impostor, NoCracksOnSharedEdges) {
    auto vertex = [](float x, float z) {
        assets::MeshCpu::Vertex v;
        v.position = glm::vec3(x, 0.0f, z);
        v.normal = glm::vec3(0.0f, 1.0f, 0.0f);
        v.uv = glm::vec2(0.5f, 0.5f);   // flat colour surface: uv is irrelevant
        return v;
    };
    assets::MeshCpu mesh;
    mesh.material_index = 0;
    mesh.node_index = 0;
    mesh.vertices = {
        vertex(8.0f, -8.0f),    // 0: C00
        vertex(8.0f, 8.0f),     // 1: C10
        vertex(-8.0f, 8.0f),    // 2: C11 == -C00
        vertex(-8.0f, -8.0f),   // 3: C01
    };
    // Shared diagonal: vertex 0 (C00) -- vertex 2 (C11), traversed as 2->0 by
    // the first triangle and 0->2 by the second (opposite directions, as any
    // interior edge of a consistently-wound mesh is).
    mesh.indices = {0, 1, 2,   0, 2, 3};

    rockgen::RockSurface flat;
    flat.base_color.width = flat.base_color.height = 1;
    flat.base_color.format = assets::Image::Format::RGB8;
    flat.base_color.pixels = {200, 150, 100};
    flat.normal.width = flat.normal.height = 1;
    flat.normal.format = assets::Image::Format::RGB8;
    flat.normal.pixels = {128, 128, 255};

    const int view_size = 31;   // odd: the origin lands on a PIXEL CENTRE
    auto imp = rockgen::bake_impostor(mesh, flat, view_size);
    ASSERT_EQ(imp.albedo.width, static_cast<std::uint32_t>(4 * view_size));

    // View 0 occupies canvas cell (0, 0). This 12x12 block is centred on the
    // view (and hence on the shared diagonal) with a wide margin inside the
    // rectangle's true silhouette on every side (the rectangle's half-extent
    // there is ~10-11 pixels; this block only reaches +-5.5 from centre).
    constexpr int kLo = 10, kHi = 21;
    for (int py = kLo; py <= kHi; ++py) {
        for (int px = kLo; px <= kHi; ++px) {
            const size_t i = (static_cast<size_t>(py) * imp.albedo.width + static_cast<size_t>(px)) * 4;
            EXPECT_GT(imp.albedo.pixels[i + 3], 0) << "px=" << px << " py=" << py;
        }
    }
}

TEST(Impostor, Deterministic) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    auto surf = rockgen::generate_rock_surface(s[0]);
    auto a = rockgen::bake_impostor(lods[1], surf, 32);
    auto b = rockgen::bake_impostor(lods[1], surf, 32);
    EXPECT_EQ(a.albedo.pixels, b.albedo.pixels);
    EXPECT_EQ(a.normal.pixels, b.normal.pixels);
}
