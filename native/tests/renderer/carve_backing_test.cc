// Backing-material gate (renderer::carve_has_backing).
//
// The hull cut (frame.cc) and the breach scoop (breach_pass.cc) both consult
// this one predicate so they cannot disagree about a carve. When they DID
// disagree — the cut being pure sphere geometry and the scoop masked by the
// fill — the gap between the two shapes was a window straight through the ship.
//
// Pure CPU: no GL context, no fixture.
#include <gtest/gtest.h>

#include <renderer/carve_field_cache.h>
#include <voxel/volume.h>

namespace {

// A volume whose cells are 10 units, origin at 0, with a solid slab occupying
// z-node `solid_z`. Everything else empty.
voxel::VoxelVolume slab(int nz, int solid_z) {
    voxel::VoxelVolume v;
    v.dims   = glm::ivec3(4, 4, nz);
    v.origin = glm::vec3(0.0f);
    v.cell   = glm::vec3(10.0f);
    v.occ.assign(static_cast<std::size_t>(4 * 4 * nz), 0);
    if (solid_z >= 0)
        for (int y = 0; y < 4; ++y)
            for (int x = 0; x < 4; ++x)
                v.occ[v.index(x, y, solid_z)] = 127;
    return v;
}

const glm::vec3 kDown(0.0f, 0.0f, 1.0f);   // outward normal = +Z, so probe -Z

// An empty volume means "no opinion" — a mod ship with no _vox.nif must keep
// its damage rather than lose it to a gate that has nothing to say.
TEST(CarveBackingTest, EmptyVolumeDoesNotGate) {
    voxel::VoxelVolume none;
    EXPECT_TRUE(renderer::carve_has_backing(none, glm::vec3(15, 15, 25), kDown));
}

// A carve sitting just above solid material finds it and is allowed to cut.
TEST(CarveBackingTest, MaterialBelowTheCarveIsBacking) {
    const voxel::VoxelVolume v = slab(4, /*solid_z=*/1);
    // Centre in node-2 space (z 20..30); marching -Z reaches the slab at z 10..20.
    EXPECT_TRUE(renderer::carve_has_backing(v, glm::vec3(15, 15, 25), kDown));
}

// The whole point: a carve over a region with nothing beneath it is refused,
// so the hull is not cut into a see-through window.
TEST(CarveBackingTest, NothingBelowTheCarveIsRefused) {
    const voxel::VoxelVolume v = slab(4, /*solid_z=*/-1);   // no material at all
    EXPECT_FALSE(renderer::carve_has_backing(v, glm::vec3(15, 15, 25), kDown));
}

// Material ABOVE the carve is not backing — the probe is directional. Without
// this the gate would pass on a hull plate it is standing on the far side of.
TEST(CarveBackingTest, MaterialAboveTheCarveIsNotBacking) {
    const voxel::VoxelVolume v = slab(4, /*solid_z=*/3);    // slab at z 30..40
    EXPECT_FALSE(renderer::carve_has_backing(v, glm::vec3(15, 15, 25), kDown));
}

// kBackingIsovalue is 1, NOT kIsovalue (64): measured on stock hulls, 39-53% of
// hull triangles sit at or outside the iso-64 surface, so gating there
// suppressed damage on 13-31% of the hull. Partial fill is real material.
TEST(CarveBackingTest, PartialFillBelowTheSolidIsovalueStillCounts) {
    voxel::VoxelVolume v = slab(4, /*solid_z=*/1);
    for (auto& b : v.occ)
        if (b) b = 8;                       // well under kIsovalue, over kBacking
    ASSERT_LT(8, renderer::CarveFieldCache::kIsovalue);
    EXPECT_TRUE(renderer::carve_has_backing(v, glm::vec3(15, 15, 25), kDown));
}

// The probe marches ~1.5 cells; material further away than that is out of reach.
// One tap at a single depth was measured to be far too strict.
TEST(CarveBackingTest, MaterialBeyondTheProbeReachIsOutOfRange) {
    const voxel::VoxelVolume v = slab(8, /*solid_z=*/0);    // slab at z 0..10
    // Centre at z 75; reach is 1.5 * 10 = 15 units, nowhere near z 10.
    EXPECT_FALSE(renderer::carve_has_backing(v, glm::vec3(15, 15, 75), kDown));
}

// A carve outside the grid entirely has nothing behind it by construction.
TEST(CarveBackingTest, CarveOutsideTheGridIsRefused) {
    const voxel::VoxelVolume v = slab(4, /*solid_z=*/1);
    EXPECT_FALSE(renderer::carve_has_backing(v, glm::vec3(500, 500, 500), kDown));
}

}  // namespace
