// native/tests/voxel/field_atlas_test.cc
//
// Packing a DistanceField's Z-slices into one GL_R8 2D atlas so it can reach
// opaque.frag as a sampler2D. The test that matters most is
// BorderReplicatesTheEdgeTexel: without a replicated border, hardware
// bilinear filtering at a slice edge blends in the neighbouring TILE's
// texels -- a different Z-slice entirely -- and the hull grows holes along
// every tile seam.
#include <gtest/gtest.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>

#include <cstdint>
#include <vector>

namespace {

std::uint8_t encode(int d) { return static_cast<std::uint8_t>(d + 128); }

// A field with a distinct, easily-inverted value per cell: v(x,y,z) =
// x*10 + y - z*5. For dims up to (9,9,9) this stays inside int8 range and is
// injective enough over the small extents this file uses that any single
// mis-indexed axis produces a different value at the sample point, so a
// wrong-axis or off-by-one bug is caught rather than accidentally matching.
voxel::DistanceField pattern_field(glm::ivec3 dims) {
    voxel::DistanceField f;
    f.dims = dims;
    f.origin = glm::vec3(0.0f);
    f.cell = glm::vec3(1.0f);
    f.scale = 1.0f;
    f.dist.resize(static_cast<std::size_t>(dims.x) * dims.y * dims.z);
    for (int z = 0; z < dims.z; ++z)
    for (int y = 0; y < dims.y; ++y)
    for (int x = 0; x < dims.x; ++x) {
        const int v = x * 10 + y - z * 5;
        f.dist[f.index(x, y, z)] = static_cast<std::int8_t>(v);
    }
    return f;
}

// A field where every cell in slice z holds the SAME value values[z] --
// used to test that tile borders don't bleed between slices.
voxel::DistanceField uniform_slices_field(glm::ivec3 dims,
                                          const std::vector<int>& values) {
    voxel::DistanceField f;
    f.dims = dims;
    f.origin = glm::vec3(0.0f);
    f.cell = glm::vec3(1.0f);
    f.scale = 1.0f;
    f.dist.resize(static_cast<std::size_t>(dims.x) * dims.y * dims.z);
    for (int z = 0; z < dims.z; ++z)
    for (int y = 0; y < dims.y; ++y)
    for (int x = 0; x < dims.x; ++x) {
        f.dist[f.index(x, y, z)] = static_cast<std::int8_t>(values[z]);
    }
    return f;
}

}  // namespace

TEST(FieldAtlas, LayoutIsRoughlySquare) {
    // dims.z = 37: sqrt(37) ~= 6.08, so tiles_x = 7, tiles_y = ceil(37/7) = 6.
    const voxel::AtlasLayout l = voxel::atlas_layout_for(glm::ivec3(8, 8, 37));
    EXPECT_GE(l.tiles_x * l.tiles_y, 37) << "grid must have room for every slice";
    EXPECT_LE(std::abs(l.tiles_x - l.tiles_y), 1)
        << "neither grid dimension may exceed the other by more than one tile";
}

TEST(FieldAtlas, LayoutCoversEverySlice) {
    for (int z : {1, 2, 16, 37, 66}) {
        const voxel::AtlasLayout l = voxel::atlas_layout_for(glm::ivec3(4, 4, z));
        EXPECT_GE(l.tiles_x * l.tiles_y, z) << "dims.z = " << z;
    }
}

TEST(FieldAtlas, DegenerateDimsYieldAnInvalidLayout) {
    EXPECT_FALSE(voxel::atlas_layout_for(glm::ivec3(0, 4, 4)).valid());
    EXPECT_FALSE(voxel::atlas_layout_for(glm::ivec3(4, 0, 4)).valid());
    EXPECT_FALSE(voxel::atlas_layout_for(glm::ivec3(4, 4, 0)).valid());

    // A real, non-empty field paired with a layout built from degenerate
    // dims must still pack to nothing: the l.valid() guard has to fire even
    // when f itself is perfectly fine, proving pack_field_to_atlas checks
    // the layout and does not merely fall back on f.empty().
    const voxel::DistanceField f = pattern_field(glm::ivec3(4, 4, 4));
    ASSERT_FALSE(f.empty());
    const voxel::AtlasLayout bad = voxel::atlas_layout_for(glm::ivec3(0, 4, 4));
    EXPECT_TRUE(voxel::pack_field_to_atlas(f, bad).empty());
}

TEST(FieldAtlas, PackedSizeMatchesTheLayout) {
    const voxel::DistanceField f = pattern_field(glm::ivec3(5, 3, 7));
    const voxel::AtlasLayout l = voxel::atlas_layout_for(f.dims);
    const std::vector<std::uint8_t> bytes = voxel::pack_field_to_atlas(f, l);
    EXPECT_EQ(bytes.size(), static_cast<std::size_t>(l.width) * l.height);
}

TEST(FieldAtlas, CellValueRoundTripsThroughTheAtlas) {
    const glm::ivec3 dims(3, 4, 5);   // dims.z = 5 forces a multi-tile grid
    const voxel::DistanceField f = pattern_field(dims);
    const voxel::AtlasLayout l = voxel::atlas_layout_for(dims);
    ASSERT_TRUE(l.valid());
    const std::vector<std::uint8_t> bytes = voxel::pack_field_to_atlas(f, l);
    ASSERT_EQ(bytes.size(), static_cast<std::size_t>(l.width) * l.height);

    // Every cell of every slice, not just a hand-picked few: with tiles_x=3
    // this exercises slices that land in different tile columns AND rows, so
    // the tile-origin arithmetic (s % tiles_x, s / tiles_x) is exercised on
    // both axes, not just the first row of tiles.
    for (int z = 0; z < dims.z; ++z)
    for (int y = 0; y < dims.y; ++y)
    for (int x = 0; x < dims.x; ++x) {
        const int tile_ox = (z % l.tiles_x) * l.tile_w;
        const int tile_oy = (z / l.tiles_x) * l.tile_h;
        const int ax = tile_ox + 1 + x;
        const int ay = tile_oy + 1 + y;
        const std::size_t atlas_i = static_cast<std::size_t>(ay) * l.width + ax;
        const std::uint8_t expected = encode(f.dist[f.index(x, y, z)]);
        EXPECT_EQ(bytes[atlas_i], expected)
            << "cell (" << x << "," << y << "," << z << ")";
    }
}

TEST(FieldAtlas, BorderReplicatesTheEdgeTexel) {
    // dims chosen so tiles_x > 1 (tiles_x=3, tiles_y=2 for dims.z=5): the
    // border check exercises a tile that is NOT at atlas origin, so a bug
    // that hardcodes tile_ox/tile_oy = 0 cannot slip through.
    const glm::ivec3 dims(4, 3, 5);
    const voxel::DistanceField f = pattern_field(dims);
    const voxel::AtlasLayout l = voxel::atlas_layout_for(dims);
    ASSERT_TRUE(l.valid());
    const std::vector<std::uint8_t> bytes = voxel::pack_field_to_atlas(f, l);

    // Check every slice: tile 0 sits at atlas origin, tile 4 (the last, at
    // z=4) sits at tile_ox=(4%3)*tile_w=tile_w, tile_oy=(4/3)*tile_h=tile_h
    // -- a non-origin tile.
    for (int z = 0; z < dims.z; ++z) {
        const int tile_ox = (z % l.tiles_x) * l.tile_w;
        const int tile_oy = (z / l.tiles_x) * l.tile_h;
        auto at = [&](int ax, int ay) {
            return bytes[static_cast<std::size_t>(ay) * l.width + ax];
        };
        auto interior = [&](int x, int y) { return encode(f.dist[f.index(x, y, z)]); };

        // Left / right edges (border column, interior rows).
        for (int y = 0; y < dims.y; ++y) {
            EXPECT_EQ(at(tile_ox + 0, tile_oy + 1 + y), interior(0, y))
                << "left border, z=" << z << " y=" << y;
            EXPECT_EQ(at(tile_ox + 1 + dims.x, tile_oy + 1 + y), interior(dims.x - 1, y))
                << "right border, z=" << z << " y=" << y;
        }
        // Top / bottom edges (border row, interior columns).
        for (int x = 0; x < dims.x; ++x) {
            EXPECT_EQ(at(tile_ox + 1 + x, tile_oy + 0), interior(x, 0))
                << "bottom border, z=" << z << " x=" << x;
            EXPECT_EQ(at(tile_ox + 1 + x, tile_oy + 1 + dims.y), interior(x, dims.y - 1))
                << "top border, z=" << z << " x=" << x;
        }
        // Four corners: both axes clamp simultaneously.
        EXPECT_EQ(at(tile_ox + 0, tile_oy + 0), interior(0, 0))
            << "bottom-left corner, z=" << z;
        EXPECT_EQ(at(tile_ox + 1 + dims.x, tile_oy + 0), interior(dims.x - 1, 0))
            << "bottom-right corner, z=" << z;
        EXPECT_EQ(at(tile_ox + 0, tile_oy + 1 + dims.y), interior(0, dims.y - 1))
            << "top-left corner, z=" << z;
        EXPECT_EQ(at(tile_ox + 1 + dims.x, tile_oy + 1 + dims.y), interior(dims.x - 1, dims.y - 1))
            << "top-right corner, z=" << z;
    }
}

TEST(FieldAtlas, SlicesDoNotBleedIntoEachOther) {
    // dims.z = 2 with tiles_x = ceil(sqrt(2)) = 2, tiles_y = 1: the two
    // tiles sit side by side, so tile 0's right border column (ax = tile_w-1)
    // is physically the immediate neighbour, in the atlas buffer, of tile 1's
    // left border column (ax = tile_w). If borders didn't replicate their
    // own slice's value, or replicated the WRONG slice's, these two adjacent
    // columns would either match (bleed) or read the unused-tile fill.
    const glm::ivec3 dims(4, 4, 2);
    const int a = -50, b = 50;
    const voxel::DistanceField f = uniform_slices_field(dims, {a, b});
    const voxel::AtlasLayout l = voxel::atlas_layout_for(dims);
    ASSERT_EQ(l.tiles_x, 2);
    ASSERT_EQ(l.tiles_y, 1);
    const std::vector<std::uint8_t> bytes = voxel::pack_field_to_atlas(f, l);

    const int tile0_right_col = l.tile_w - 1;   // slice 0's right border
    const int tile1_left_col = l.tile_w;        // slice 1's left border, adjacent

    for (int ay = 0; ay < l.tile_h; ++ay) {
        EXPECT_EQ(bytes[static_cast<std::size_t>(ay) * l.width + tile0_right_col], encode(a))
            << "tile 0's border must hold slice 0's own value, row " << ay;
        EXPECT_EQ(bytes[static_cast<std::size_t>(ay) * l.width + tile1_left_col], encode(b))
            << "tile 1's border must hold slice 1's own value, row " << ay;
    }
}

TEST(FieldAtlas, EmptyFieldPacksToNothing) {
    voxel::DistanceField f;                 // default: dims {0,0,0}, no dist
    f.dims = glm::ivec3(4, 4, 4);           // non-degenerate shape...
    ASSERT_TRUE(f.empty());                 // ...but dist was never populated
    const voxel::AtlasLayout l = voxel::atlas_layout_for(f.dims);
    ASSERT_TRUE(l.valid());                 // layout itself is fine
    EXPECT_TRUE(voxel::pack_field_to_atlas(f, l).empty())
        << "an empty field must not crash and must pack to nothing, even "
           "when paired with an otherwise-valid layout";
}

TEST(FieldAtlas, UnusedTilesReadAsEmptySpace) {
    // dims.z = 3: tiles_x = ceil(sqrt(3)) = 2, tiles_y = ceil(3/2) = 2, so the
    // grid has 4 tile slots for 3 slices -- tile index 3 is unused.
    const glm::ivec3 dims(4, 4, 3);
    const voxel::DistanceField f = pattern_field(dims);
    const voxel::AtlasLayout l = voxel::atlas_layout_for(dims);
    ASSERT_EQ(l.tiles_x * l.tiles_y, 4);
    ASSERT_EQ(l.slices, 3);
    const std::vector<std::uint8_t> bytes = voxel::pack_field_to_atlas(f, l);

    const int unused_tile_ox = (3 % l.tiles_x) * l.tile_w;
    const int unused_tile_oy = (3 / l.tiles_x) * l.tile_h;
    for (int y = 0; y < l.tile_h; ++y)
    for (int x = 0; x < l.tile_w; ++x) {
        const int ax = unused_tile_ox + x;
        const int ay = unused_tile_oy + y;
        EXPECT_EQ(bytes[static_cast<std::size_t>(ay) * l.width + ax], encode(127))
            << "unused tile must read fully outside (d=127), not as hull, at ("
            << x << "," << y << ")";
    }
}
