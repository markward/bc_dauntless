// native/tests/voxel/voxelize_test.cc
#include <gtest/gtest.h>
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

TEST(CollectHullTriangles, TransformsVertsToBodyFrame) {
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
