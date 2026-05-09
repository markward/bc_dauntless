// native/src/assets/include/assets/mesh.h
#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include <glm/glm.hpp>
#include <glad/glad.h>

namespace assets {

struct MeshCpu {
    struct Vertex {
        glm::vec3   position{};
        glm::vec3   normal{};
        glm::vec2   uv{};
        glm::u8vec4 color{255, 255, 255, 255};
        glm::u8vec4 bone_indices{0, 0, 0, 0};
        glm::u8vec4 bone_weights{0, 0, 0, 0};
    };

    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> indices;
    std::vector<std::vector<glm::vec2>> extra_uvs;
    int material_index = -1;
    int node_index = -1;
};

class Mesh {
public:
    Mesh() = default;
    Mesh(GLuint vao, GLuint vbo, GLuint ebo,
         std::uint32_t index_count, int material_index, int node_index) noexcept;
    Mesh(Mesh&&) noexcept;
    Mesh& operator=(Mesh&&) noexcept;
    Mesh(const Mesh&) = delete;
    Mesh& operator=(const Mesh&) = delete;
    ~Mesh();

    GLuint vao() const noexcept { return vao_; }
    GLuint vbo() const noexcept { return vbo_; }
    GLuint ebo() const noexcept { return ebo_; }
    std::uint32_t index_count() const noexcept { return index_count_; }
    int material_index() const noexcept { return material_index_; }
    int node_index() const noexcept { return node_index_; }

    const std::optional<MeshCpu>& cpu_data() const noexcept { return cpu_data_; }
    void set_cpu_data(MeshCpu data) { cpu_data_ = std::move(data); }

    // Reserved for future LOD chains; empty in v1.
    const std::vector<Mesh>& lod_chain() const noexcept { return lod_chain_; }

private:
    GLuint vao_ = 0;
    GLuint vbo_ = 0;
    GLuint ebo_ = 0;
    std::uint32_t index_count_ = 0;
    int material_index_ = -1;
    int node_index_ = -1;
    std::optional<MeshCpu> cpu_data_;
    std::vector<Mesh> lod_chain_;
};

}  // namespace assets
