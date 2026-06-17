#include <gtest/gtest.h>
#include <voxel/dual_contour.h>
#include <glm/glm.hpp>
#include <voxel/voxelize.h>
#include <voxel/volume.h>
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>

TEST(QEF, ThreeOrthogonalPlanesGiveCorner) {
    // three axis planes through the point (2,3,4)
    std::vector<voxel::Plane> ps = {
        {{1,0,0}, 2.0f}, {{0,1,0}, 3.0f}, {{0,0,1}, 4.0f}};
    glm::vec3 v = voxel::solve_qef(ps, /*fallback=*/glm::vec3(0,0,0));
    EXPECT_NEAR(v.x, 2.0f, 1e-3);
    EXPECT_NEAR(v.y, 3.0f, 1e-3);
    EXPECT_NEAR(v.z, 4.0f, 1e-3);
}

TEST(QEF, SinglePlaneVertexLiesOnPlaneNearSeed) {
    std::vector<voxel::Plane> ps = {{{0,0,1}, 5.0f}};   // z = 5
    glm::vec3 v = voxel::solve_qef(ps, glm::vec3(1,1,1));
    EXPECT_NEAR(v.z, 5.0f, 1e-3);                        // on the plane
    EXPECT_NEAR(v.x, 1.0f, 1e-2);                        // x,y pulled toward seed
    EXPECT_NEAR(v.y, 1.0f, 1e-2);
}

TEST(QEF, NoPlanesReturnsFallback) {
    glm::vec3 v = voxel::solve_qef({}, glm::vec3(7,8,9));
    EXPECT_NEAR(v.x,7,1e-4); EXPECT_NEAR(v.y,8,1e-4); EXPECT_NEAR(v.z,9,1e-4);
}

TEST(DualContour, SyntheticBoxProducesSurface) {
    // 8^3 fill, solid (127) in an inner box [2..5]^3, empty elsewhere; a few axis planes.
    voxel::VoxelVolume v; v.dims={8,8,8}; v.origin={0,0,0}; v.cell={1,1,1};
    v.occ.assign(8*8*8,0);
    for(int z=2;z<=5;++z)for(int y=2;y<=5;++y)for(int x=2;x<=5;++x) v.occ[v.index(x,y,z)]=127;
    std::vector<glm::vec4> palette = {   // 6 axis planes bounding the box (centers at 2.5 / 5.5)
        {1,0,0,2.5f},{-1,0,0,-5.5f},{0,1,0,2.5f},{0,-1,0,-5.5f},{0,0,1,2.5f},{0,0,-1,-5.5f}};
    voxel::Mesh m = voxel::dual_contour(v, 64, palette);
    EXPECT_GT(m.positions.size(), 0u);
    EXPECT_EQ(m.indices.size() % 3u, 0u);
    // all verts within the grid bounds
    for (auto& p : m.positions) {
        EXPECT_GE(p.x, -1.f); EXPECT_LE(p.x, 9.f);
    }
}

TEST(DualContour, GalaxyExtractsRecognizableHull) {
    auto path = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)/"game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(path)) GTEST_SKIP() << "asset absent";
    auto f = nif::load(path);
    const nif::NiBinaryVoxelData* vd=nullptr;
    for(auto&b:f.blocks) if(auto*q=std::get_if<nif::NiBinaryVoxelData>(&b)) vd=q;
    ASSERT_NE(vd,nullptr);
    voxel::VoxelVolume fill = voxel::from_nif_voxel_data(*vd);
    voxel::SurfaceData s = voxel::from_nif_surface(*vd);
    voxel::Mesh m = voxel::dual_contour(fill, 64, s.planes);
    EXPECT_GT(m.positions.size(), 500u);          // a substantial surface
    voxel::write_obj(m, "/tmp/galaxy_dc.obj");     // for manual eyeball
    // sanity: mesh AABB sits within the grid AABB (= fill origin..origin+dims*cell)
    glm::vec3 mn(1e30f),mx(-1e30f);
    for(auto&p:m.positions){ mn=glm::min(mn,p); mx=glm::max(mx,p); }
    glm::vec3 gmin = fill.origin, gmax = fill.origin + glm::vec3(fill.dims)*fill.cell;
    EXPECT_GE(mn.x, gmin.x-fill.cell.x); EXPECT_LE(mx.x, gmax.x+fill.cell.x);
}
