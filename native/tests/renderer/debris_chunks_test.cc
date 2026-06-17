#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <voxel/volume.h>
#include "debris_chunks.h"  // relative include — in same renderer src tree

namespace {
// Solid 4^3 fill with all voxels occupied.
voxel::VoxelVolume solid_fill_4() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f,  1.f,  1.f};
    v.occ.assign(64, 127);
    return v;
}
} // namespace

TEST(SampleChunkOrigins, DeterministicForFixedSeed) {
    auto fill = solid_fill_4();
    auto a = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 42u, 8);
    auto b = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 42u, 8);
    ASSERT_EQ(a.size(), b.size());
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_FLOAT_EQ(a[i].x, b[i].x);
        EXPECT_FLOAT_EQ(a[i].y, b[i].y);
        EXPECT_FLOAT_EQ(a[i].z, b[i].z);
    }
}

TEST(SampleChunkOrigins, CountCappedByMaxChunks) {
    auto fill = solid_fill_4();
    auto origins = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 1u, 5);
    EXPECT_LE(origins.size(), 5u);
}

TEST(SampleChunkOrigins, AllOriginsWithinRadius) {
    auto fill = solid_fill_4();
    auto origins = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 7u, 16);
    for (const auto& o : origins) {
        EXPECT_LE(glm::length(o), 3.f + 0.87f)  // allow half-diagonal of 1-unit cell
            << "origin outside carve sphere + cell tolerance";
    }
}

TEST(ChunkTransform, PositionAdvancesWithAge) {
    // At age=0 the chunk is at its origin; at age>0 it has moved outward.
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 breach_center{0.f, 0.f, 0.f};
    auto t0 = renderer::chunk_transform(origin, breach_center, 0.0f, 1u, 0);
    auto t1 = renderer::chunk_transform(origin, breach_center, 0.5f, 1u, 0);
    EXPECT_GT(glm::length(t1.pos_body - origin),
              glm::length(t0.pos_body - origin))
        << "chunk must move away from origin with increasing age";
}

TEST(ChunkTransform, AlphaFadesToZeroAtDebrisLife) {
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 center{0.f, 0.f, 0.f};
    auto t_alive = renderer::chunk_transform(origin, center, 0.1f, 1u, 0);
    auto t_dead  = renderer::chunk_transform(origin, center,
                                              scenegraph::kDebrisLife + 0.01f,
                                              1u, 0);
    EXPECT_GT(t_alive.alpha, 0.5f);
    EXPECT_FLOAT_EQ(t_dead.alpha, 0.f);
}

TEST(ChunkTransform, DifferentSeedsProduceDifferentDirs) {
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 center{0.f, 0.f, 0.f};
    auto ta = renderer::chunk_transform(origin, center, 0.5f, 42u, 0);
    auto tb = renderer::chunk_transform(origin, center, 0.5f, 99u, 0);
    // Different seeds must produce different positions (extremely unlikely to
    // collide with 64-bit hashing).
    EXPECT_NE(ta.pos_body, tb.pos_body);
}
