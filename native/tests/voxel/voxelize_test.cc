// native/tests/voxel/voxelize_test.cc
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <voxel/voxelize.h>
#include <assets/model.h>

// Build a 1-triangle model: identity node, one mesh with 3 verts.
// assets::Mesh is a GPU object; we default-construct it (vao/vbo/ebo = 0,
// which OpenGL treats as no-op on delete) and set_cpu_data with our triangle.
// The destructor calls glDelete*(0) which is a harmless no-op in any GL impl
// and also in a no-GL test binary because we never call the gl functions
// that register those objects.
static assets::Model one_triangle_model() {
    assets::Model m;

    // Node: root, owns mesh 0, identity transform.
    assets::Node n;
    n.parent_index = -1;
    n.meshes = {0};
    // local_transform defaults to identity (glm::mat4{1.0f} in the struct).
    m.nodes = {n};
    m.root_node = 0;

    // CPU mesh: 3 vertices, 1 triangle.
    assets::MeshCpu cpu;
    cpu.vertices = {
        assets::MeshCpu::Vertex{ .position = {0.f, 0.f, 0.f} },
        assets::MeshCpu::Vertex{ .position = {2.f, 0.f, 0.f} },
        assets::MeshCpu::Vertex{ .position = {0.f, 2.f, 0.f} },
    };
    cpu.indices = {0, 1, 2};

    assets::Mesh mesh;  // default-constructed, vao/vbo/ebo = 0
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    return m;
}

// Fix m2: renamed from TransformsVertsToBodyFrame → OutputsWorldSpaceTriangle.
// The test uses an identity node so the values pass through unchanged; it
// verifies that vertices end up in accumulated world space (here = body space
// because the transform is identity).
TEST(CollectHullTriangles, OutputsWorldSpaceTriangle) {
    auto m = one_triangle_model();
    auto tris = voxel::collect_hull_triangles(m);
    ASSERT_EQ(tris.size(), 1u);
    EXPECT_FLOAT_EQ(tris[0].a.x, 0.f);
    EXPECT_FLOAT_EQ(tris[0].b.x, 2.f);
    EXPECT_FLOAT_EQ(tris[0].c.y, 2.f);
}

TEST(CollectHullTriangles, EmptyModelReturnsEmpty) {
    assets::Model m;
    auto tris = voxel::collect_hull_triangles(m);
    EXPECT_TRUE(tris.empty());
}

TEST(CollectHullTriangles, MeshWithNoCpuDataSkipped) {
    assets::Model m;
    assets::Node n;
    n.parent_index = -1;
    n.meshes = {0};
    m.nodes = {n};
    m.root_node = 0;

    // Mesh with no cpu_data set — should be silently skipped.
    assets::Mesh mesh;  // no set_cpu_data call
    m.meshes.push_back(std::move(mesh));

    auto tris = voxel::collect_hull_triangles(m);
    EXPECT_TRUE(tris.empty());
}

// Fix I1: pins the transform MULTIPLICATION ORDER (root-first / parent-first).
//
// Tree:
//   Node 0 (root, parent_index=-1): R_z(90°)  — rotate 90° about Z
//   Node 1 (child, parent_index=0): T_x(+1)   — translate +1 along X
//
// A vertex at the child-local origin (0,0,0) must transform as:
//   world = R_z(90°) * T_x(1) * (0,0,0,1)
//         = R_z(90°) * (1,0,0,1)
//         = (0,1,0,1)      ← expect x≈0, y≈1, z≈0
//
// If the order were reversed (child-first): T_x(1) * R_z(90°) * (0,0,0,1)
//   = T_x(1) * (0,0,0) = (1,0,0) — WRONG; the test would catch that.
TEST(CollectHullTriangles, TransformOrderIsRootFirst) {
    assets::Model m;

    // Root node: 90° rotation about Z.
    assets::Node root;
    root.parent_index = -1;
    root.meshes = {};
    root.local_transform =
        glm::rotate(glm::mat4(1.0f), glm::radians(90.0f), glm::vec3(0, 0, 1));
    m.nodes.push_back(root);
    m.root_node = 0;

    // Child node: translate +1 along X; owns mesh 0.
    assets::Node child;
    child.parent_index = 0;
    child.meshes = {0};
    child.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(1.0f, 0.0f, 0.0f));
    m.nodes.push_back(child);

    // Mesh: single triangle whose FIRST vertex is the child-local origin.
    assets::MeshCpu cpu;
    cpu.vertices = {
        assets::MeshCpu::Vertex{ .position = {0.f, 0.f, 0.f} },  // origin — the one we check
        assets::MeshCpu::Vertex{ .position = {1.f, 0.f, 0.f} },
        assets::MeshCpu::Vertex{ .position = {0.f, 1.f, 0.f} },
    };
    cpu.indices = {0, 1, 2};

    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    auto tris = voxel::collect_hull_triangles(m);
    ASSERT_EQ(tris.size(), 1u);

    // tris[0].a is the child-local origin (0,0,0) after root-first transform.
    // R_z(90°) * T_x(1) * (0,0,0,1) → (0,1,0)
    constexpr float kEps = 1e-5f;
    EXPECT_NEAR(tris[0].a.x, 0.0f, kEps);
    EXPECT_NEAR(tris[0].a.y, 1.0f, kEps);
    EXPECT_NEAR(tris[0].a.z, 0.0f, kEps);
}

TEST(SurfaceVoxelize, MarksVoxelsTrianglePassesThrough) {
    voxel::VoxelVolume v;
    v.dims = {8, 8, 8};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(8 * 8 * 8, 0);
    // A triangle lying in the z=4 plane spanning x,y in [1,6].
    std::vector<voxel::Tri> tris = {
        {{1,1,4},{6,1,4},{1,6,4}}
    };
    voxel::surface_voxelize(v, tris);
    EXPECT_GT(v.solid_count(), 0u);
    EXPECT_TRUE(v.solid(2, 2, 4));   // inside the triangle, on its plane
    EXPECT_FALSE(v.solid(2, 2, 0));  // far from the triangle
}

TEST(Solidify, FillsHollowBoxInterior) {
    voxel::VoxelVolume v;
    v.dims = {6, 6, 6};
    v.origin = {0.f, 0.f, 0.f};
    v.cell = {1.f, 1.f, 1.f};
    v.occ.assign(6 * 6 * 6, 0);
    // Hollow shell: mark the outer faces of a 1..4 cube as solid, interior empty.
    for (int z = 1; z <= 4; ++z)
    for (int y = 1; y <= 4; ++y)
    for (int x = 1; x <= 4; ++x) {
        bool shell = (x==1||x==4||y==1||y==4||z==1||z==4);
        if (shell) v.set(x, y, z, true);
    }
    EXPECT_FALSE(v.solid(2, 2, 2));        // interior empty before
    voxel::solidify(v);
    EXPECT_TRUE(v.solid(2, 2, 2));         // interior filled after
    EXPECT_FALSE(v.solid(0, 0, 0));        // exterior still empty
}

// Build a cube triangle-soup (not wrapped in a Model) for voxelize_into tests.
static std::vector<voxel::Tri> cube_tris(float lo, float hi) {
    const float L = lo, H = hi;
    glm::vec3 c[8] = {
        {L,L,L},{H,L,L},{H,H,L},{L,H,L},
        {L,L,H},{H,L,H},{H,H,H},{L,H,H}
    };
    int f[12][3] = {
        {0,1,2},{0,2,3},
        {4,6,5},{4,7,6},
        {0,4,5},{0,5,1},
        {1,5,6},{1,6,2},
        {2,6,7},{2,7,3},
        {3,7,4},{3,4,0}
    };
    std::vector<voxel::Tri> tris;
    tris.reserve(12);
    for (int i = 0; i < 12; ++i)
        tris.push_back({c[f[i][0]], c[f[i][1]], c[f[i][2]]});
    return tris;
}

// voxelize_into with explicit grid: a cube [0,4]^3 on a 16^3 grid with the
// same grid parameters as voxelize() would compute (1-voxel margin).
// Central voxels must be solid; the grid dims/origin/cell must match exactly.
TEST(VoxelizeInto, SolidCubeOnExplicitGrid) {
    const glm::ivec3 dims(16, 16, 16);
    // Mirror what voxelize() computes: extent/(dims-2) cell, mn-cell origin.
    const float lo = 0.f, hi = 4.f;
    const float extent = hi - lo;
    const glm::vec3 cell(extent / float(dims.x - 2),
                         extent / float(dims.y - 2),
                         extent / float(dims.z - 2));
    const glm::vec3 origin(lo - cell.x, lo - cell.y, lo - cell.z);

    auto tris = cube_tris(lo, hi);
    voxel::VoxelVolume v = voxel::voxelize_into(tris, dims, origin, cell);

    EXPECT_EQ(v.dims, dims);
    EXPECT_EQ(v.occ.size(), std::size_t(16 * 16 * 16));
    // Should be mostly solid.
    EXPECT_GT(v.solid_count(), 100u);
    // Centre voxel must be solid.
    glm::ivec3 mid = dims / 2;
    EXPECT_TRUE(v.solid(mid.x, mid.y, mid.z));
}

// voxelize_into with a SHIFTED origin: same cube tris, but place the grid
// so the cube sits in the upper-right quadrant of the volume. Voxels in the
// lower-left corner must be empty; the cube interior must be solid.
TEST(VoxelizeInto, ExplicitGridSuppressesOutOfRangeTris) {
    const glm::ivec3 dims(16, 16, 16);
    // The cube lives at [0,4]^3 but we shift origin so it fills voxels ~[4,12].
    const glm::vec3 cell(0.5f, 0.5f, 0.5f);
    const glm::vec3 origin(-2.f, -2.f, -2.f);  // voxel 0 center at (-1.75, ...)

    auto tris = cube_tris(0.f, 4.f);
    voxel::VoxelVolume v = voxel::voxelize_into(tris, dims, origin, cell);

    EXPECT_EQ(v.dims, dims);
    // Interior voxels around the centre of the cube must be solid.
    // Cube [0,4] → centre (2,2,2). In grid: voxel ~ (2-origin)/cell = (8,8,8).
    EXPECT_TRUE(v.solid(8, 8, 8));
    // Voxel at (0,0,0): centre = origin + 0.5*cell = (-1.75,...). Outside cube → empty.
    EXPECT_FALSE(v.solid(0, 0, 0));
}

TEST(Voxelize, SolidCubeModelIsMostlySolid) {
    // Axis-aligned solid cube hull with vertices at x,y,z in [0,4], 12 triangles.
    assets::Model m;
    assets::Node n; n.parent_index = -1; n.meshes = {0};
    m.nodes = {n}; m.root_node = 0;

    glm::vec3 c[8] = {
        {0,0,0},{4,0,0},{4,4,0},{0,4,0},
        {0,0,4},{4,0,4},{4,4,4},{0,4,4}
    };
    int f[12][3] = {
        {0,1,2},{0,2,3},   // bottom (-Z face)
        {4,6,5},{4,7,6},   // top    (+Z face)
        {0,4,5},{0,5,1},   // front  (-Y face)
        {1,5,6},{1,6,2},   // right  (+X face)
        {2,6,7},{2,7,3},   // back   (+Y face)
        {3,7,4},{3,4,0}    // left   (-X face)
    };

    assets::MeshCpu cpu;
    for (int i = 0; i < 8; ++i)
        cpu.vertices.push_back(assets::MeshCpu::Vertex{ .position = c[i] });
    for (int i = 0; i < 12; ++i) {
        cpu.indices.push_back(static_cast<uint32_t>(f[i][0]));
        cpu.indices.push_back(static_cast<uint32_t>(f[i][1]));
        cpu.indices.push_back(static_cast<uint32_t>(f[i][2]));
    }

    assets::Mesh mesh;  // default-constructed, vao/vbo/ebo = 0
    mesh.set_cpu_data(std::move(cpu));
    m.meshes.push_back(std::move(mesh));

    voxel::VoxelVolume v = voxel::voxelize(m, glm::ivec3(16, 16, 16));
    // A solid 4x4x4 box in a 16^3 grid sized to a small margin should fill
    // a large, contiguous central region.
    EXPECT_GT(v.solid_count(), 100u);
    glm::ivec3 mid = v.dims / 2;
    EXPECT_TRUE(v.solid(mid.x, mid.y, mid.z));
}
