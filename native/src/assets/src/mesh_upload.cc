#include "mesh_upload.h"

#include <assets/texture.h>  // for GlUploadError

#include "gl_handle.h"

#include <cstddef>
#include <cstdio>
#include <string>

namespace assets {

namespace {

void check_gl(const char* op) {
    GLenum err = glGetError();
    if (err == GL_NO_ERROR) return;
    while (glGetError() != GL_NO_ERROR) {}
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%X", err);
    throw GlUploadError(
        std::string("GL error during ") + op + ": 0x" + buf, err);
}

}  // namespace

Mesh upload_mesh(const MeshCpu& cpu) {
    GLuint vao = 0, vbo = 0, ebo = 0;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glGenBuffers(1, &ebo);
    detail::VertexArrayHandle vao_h(vao);
    detail::BufferHandle      vbo_h(vbo);
    detail::BufferHandle      ebo_h(ebo);

    glBindVertexArray(vao);

    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(
        GL_ARRAY_BUFFER,
        static_cast<GLsizeiptr>(cpu.vertices.size() * sizeof(MeshCpu::Vertex)),
        cpu.vertices.data(), GL_STATIC_DRAW);

    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(
        GL_ELEMENT_ARRAY_BUFFER,
        static_cast<GLsizeiptr>(cpu.indices.size() * sizeof(std::uint32_t)),
        cpu.indices.data(), GL_STATIC_DRAW);

    using V = MeshCpu::Vertex;
    const GLsizei stride = sizeof(V);

    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, position)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, normal)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, uv)));
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride,
                          reinterpret_cast<void*>(offsetof(V, color)));
    glEnableVertexAttribArray(4);
    glVertexAttribIPointer(4, 4, GL_UNSIGNED_BYTE, stride,
                           reinterpret_cast<void*>(offsetof(V, bone_indices)));
    glEnableVertexAttribArray(5);
    glVertexAttribPointer(5, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride,
                          reinterpret_cast<void*>(offsetof(V, bone_weights)));

    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);

    check_gl("upload_mesh");
    return Mesh(
        vao_h.release(), vbo_h.release(), ebo_h.release(),
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

}  // namespace assets
