// Cavity-depth probe (renderer::carve_cavity_depth_cells).
//
// The breach scoop draws the damage sphere's inner surface masked by the voxel
// fill. That construction degenerates when the fill is thin: BC's authored
// volumes are only a handful of nodes deep through a hull's vertical axis
// (measured: Galaxy 9, Vorcha 7, BirdOfPrey 6, Sovereign 5, Akira 5, Galor 3),
// so on a thin ship the only place the mask passes is the mid-plane and the
// "interior" collapses into a flat sheet of damage material down the centre of
// the ship — visible through every breach, and impossible to cut away because
// it is not hull.
//
// Worse, that sheet backfills the hole: a carve near a hull edge discards the
// hull fragments as it should, then the scoop paints a slab across the gap, so
// a breach reads as a crust rather than as a hole.
//
// So the scoop asks how DEEP the material runs before it draws. Too thin for a
// convincing cavity and it draws nothing: you see straight through, and a hole
// reads as a hole.
//
// Pure CPU: no GL context, no fixture.
#include <gtest/gtest.h>

#include <renderer/carve_field_cache.h>
#include <voxel/volume.h>

namespace {

// A volume whose cells are 10 units, origin at 0, solid for z-nodes
// [solid_lo, solid_hi]. Everything else empty.
voxel::VoxelVolume slab(int nz, int solid_lo, int solid_hi) {
    voxel::VoxelVolume v;
    v.dims   = glm::ivec3(4, 4, nz);
    v.origin = glm::vec3(0.0f);
    v.cell   = glm::vec3(10.0f);
    v.occ.assign(static_cast<std::size_t>(4 * 4 * nz), 0);
    for (int z = solid_lo; z <= solid_hi && z < nz; ++z)
        if (z >= 0)
            for (int y = 0; y < 4; ++y)
                for (int x = 0; x < 4; ++x)
                    v.occ[v.index(x, y, z)] = 127;
    return v;
}

const glm::vec3 kUp(0.0f, 0.0f, 1.0f);   // outward normal = +Z, so probe -Z

// No volume to consult means no opinion: a mod ship with no _vox.nif must keep
// its scoop rather than lose it to a probe that has nothing to say. Mirrors
// carve_has_backing's empty-volume behaviour.
TEST(CarveCavityTest, EmptyVolumeReportsAmpleDepth) {
    voxel::VoxelVolume none;
    EXPECT_GE(renderer::carve_cavity_depth_cells(none, glm::vec3(15, 15, 25), kUp),
              renderer::CarveFieldCache::kMinCavityCells);
}

// A deep block of material: the probe should report a cavity worth drawing.
TEST(CarveCavityTest, DeepMaterialReportsDeepCavity) {
    // Solid from the top node all the way down.
    const voxel::VoxelVolume v = slab(8, /*lo=*/0, /*hi=*/7);
    const float d = renderer::carve_cavity_depth_cells(
        v, glm::vec3(15, 15, 75), kUp);
    EXPECT_GE(d, renderer::CarveFieldCache::kMinCavityCells);
}

// The Galor case: a hull barely one cell thick. Material IS present — so
// carve_has_backing still allows the cut — but there is nowhere near enough of
// it to build a cavity, so the scoop must stand down.
TEST(CarveCavityTest, ThinSlabIsTooShallowForACavity) {
    const voxel::VoxelVolume v = slab(8, /*lo=*/6, /*hi=*/6);   // one node thick
    const float d = renderer::carve_cavity_depth_cells(
        v, glm::vec3(15, 15, 75), kUp);
    EXPECT_LT(d, renderer::CarveFieldCache::kMinCavityCells);
    // ...but the cut itself is still allowed: these two answer different
    // questions and must not be conflated.
    EXPECT_TRUE(renderer::carve_has_backing(v, glm::vec3(15, 15, 75), kUp));
}

// Nothing at all beneath: no cavity.
TEST(CarveCavityTest, NoMaterialReportsNoCavity) {
    const voxel::VoxelVolume v = slab(8, /*lo=*/-1, /*hi=*/-1);
    EXPECT_FLOAT_EQ(renderer::carve_cavity_depth_cells(
                        v, glm::vec3(15, 15, 75), kUp), 0.0f);
}

// Depth is measured INWARD along -normal. Material sitting on the outward side
// is not cavity, or a carve on the underside of a hull would report the hull
// above it as depth.
TEST(CarveCavityTest, MaterialAboveTheCarveIsNotCavity) {
    const voxel::VoxelVolume v = slab(8, /*lo=*/7, /*hi=*/7);
    // Probe point below the slab, normal pointing up: marching -Z goes away.
    EXPECT_FLOAT_EQ(renderer::carve_cavity_depth_cells(
                        v, glm::vec3(15, 15, 65), kUp), 0.0f);
}

// A carve entirely off the grid has nothing under it.
TEST(CarveCavityTest, CarveOutsideTheGridReportsNoCavity) {
    const voxel::VoxelVolume v = slab(8, /*lo=*/0, /*hi=*/7);
    EXPECT_FLOAT_EQ(renderer::carve_cavity_depth_cells(
                        v, glm::vec3(500, 500, 75), kUp), 0.0f);
}

// Deeper material must not report LESS cavity than shallower material.
TEST(CarveCavityTest, DepthIsMonotonicInMaterialThickness) {
    const float thin = renderer::carve_cavity_depth_cells(
        slab(8, 5, 6), glm::vec3(15, 15, 75), kUp);
    const float thick = renderer::carve_cavity_depth_cells(
        slab(8, 2, 6), glm::vec3(15, 15, 75), kUp);
    EXPECT_GT(thick, thin);
}

}  // namespace
