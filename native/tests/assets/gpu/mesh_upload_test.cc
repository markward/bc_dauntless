#include <gtest/gtest.h>
#include <glad/glad.h>

#include "gl_fixture.h"
#include "mesh_upload.h"

class MeshUploadTest : public assets_test::GLContext {};

TEST_F(MeshUploadTest, UploadsTriangle) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(3);
    cpu.vertices[0].position = {0.0f, 0.0f, 0.0f};
    cpu.vertices[1].position = {1.0f, 0.0f, 0.0f};
    cpu.vertices[2].position = {0.0f, 1.0f, 0.0f};
    cpu.indices = {0, 1, 2};
    cpu.material_index = 5;
    cpu.node_index = 11;

    auto mesh = assets::upload_mesh(cpu);
    EXPECT_NE(mesh.vao(), 0u);
    EXPECT_NE(mesh.vbo(), 0u);
    EXPECT_NE(mesh.ebo(), 0u);
    EXPECT_EQ(mesh.index_count(), 3u);
    EXPECT_EQ(mesh.material_index(), 5);
    EXPECT_EQ(mesh.node_index(), 11);
    EXPECT_TRUE(glIsVertexArray(mesh.vao()));
    EXPECT_TRUE(glIsBuffer(mesh.vbo()));
    EXPECT_TRUE(glIsBuffer(mesh.ebo()));
}

TEST_F(MeshUploadTest, MovedFromMeshIsZero) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(1);
    cpu.indices = {0};

    auto a = assets::upload_mesh(cpu);
    auto b = std::move(a);
    EXPECT_EQ(a.vao(), 0u);
    EXPECT_NE(b.vao(), 0u);
    EXPECT_TRUE(glIsVertexArray(b.vao()));
}

TEST_F(MeshUploadTest, AllVertexAttributesEnabled) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(1);
    cpu.indices = {0};

    auto mesh = assets::upload_mesh(cpu);
    glBindVertexArray(mesh.vao());
    // Locations 0-7: position, normal, uv, color, bone_indices, bone_weights,
    // uv1, crushability.
    for (int loc = 0; loc < 8; ++loc) {
        GLint enabled = 0;
        glGetVertexAttribiv(loc, GL_VERTEX_ATTRIB_ARRAY_ENABLED, &enabled);
        EXPECT_EQ(enabled, GL_TRUE) << "attribute location " << loc << " not enabled";
    }
    glBindVertexArray(0);
}
