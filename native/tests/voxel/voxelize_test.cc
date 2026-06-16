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
