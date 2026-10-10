// native/tests/host/model_identity_maps_test.cc
//
// model_identity's per-mesh "maps" computation (spec 2026-10-09-bridge-pbr),
// tested against a hand-built assets::Model so an out-of-range
// material_index() -- which no NIF-loaded model produces, so the Python
// binding has no fixture for it -- is exercised directly instead of only by
// code review.
#include <gtest/gtest.h>

#include "model_identity_maps.h"

#include <assets/model.h>

namespace {

using S = assets::Material::StageSlot;

assets::Model model_with_one_material_with_roughness() {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Roughness)].texture_index = 0;
    model.materials.push_back(mat);
    return model;
}

}  // namespace

TEST(SafeMaterialIndex, InRangeIndexPassesThrough) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 0), 0);
}

TEST(SafeMaterialIndex, NegativeIndexStaysNegativeOne) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, -1), -1);
}

TEST(SafeMaterialIndex, IndexEqualToSizeIsOutOfRange) {
    // model.materials.size() == 1, so index 1 is one past the end --
    // material_or_default would read model.materials[1] with operator[],
    // out of bounds, if this were not clamped first.
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 1), -1);
}

TEST(SafeMaterialIndex, FarOutOfRangeIndexIsClamped) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 1000), -1);
}

TEST(SafeMaterialIndex, EmptyMaterialsListIndexZeroIsOutOfRange) {
    assets::Model model;  // model.materials is empty
    EXPECT_EQ(dauntless::safe_material_index(model, 0), -1);
}

TEST(MeshIdentityMaps, InRangeIndexReadsTheRealMaterialStages) {
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 0);
    EXPECT_TRUE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, OutOfRangeIndexIsAllFalseNotAnOutOfBoundsRead) {
    // Regression test: before the bounds check was shared with
    // safe_material_index, this called assets::material_or_default(model, 1)
    // directly, which indexes model.materials[1] via operator[] with no
    // bounds check of its own -- an out-of-bounds read on a 1-element
    // vector. This pins the all-false fallback as the intended behaviour;
    // confirmed live by temporarily reverting mesh_identity_maps to the
    // unguarded call, which turned this into a read of whatever garbage
    // byte followed the vector's single element (see the task report).
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 1);
    EXPECT_FALSE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, NoMaterialIndexIsAllFalse) {
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, -1);
    EXPECT_FALSE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, AllThreeStagesReadIndependently) {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Roughness)].texture_index = 0;
    mat.stages[static_cast<std::size_t>(S::Metalness)].texture_index = 1;
    mat.stages[static_cast<std::size_t>(S::Bump)].texture_index = 2;
    model.materials.push_back(mat);
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 0);
    EXPECT_TRUE(maps.roughness);
    EXPECT_TRUE(maps.metalness);
    EXPECT_TRUE(maps.normal);
}

TEST(MeshIdentityMaps, ReportsAnEmissiveMap) {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Emissive)].texture_index = 0;
    model.materials.push_back(mat);
    EXPECT_TRUE(dauntless::mesh_identity_maps(model, 0).emissive);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model, -1).emissive);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model_with_one_material_with_roughness(), 0).emissive);
}
