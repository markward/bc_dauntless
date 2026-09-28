// native/src/assets/include/assets/mesh.h
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
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
        /// Optional second UV channel. Populated for shapes whose
        /// material binds a Dark-slot lightmap texture at uv_set=1 (BC
        /// bridge floors, doors, wall insets). Zero for everything else;
        /// shaders that don't sample uv1 ignore it.
        glm::vec2   uv1{};
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

    /// Source NiTriShape name (`av.obj.name`) this mesh was built from, set
    /// by build_model; empty for meshes built any other way (upload_mesh
    /// callers, composed officer heads). Hull decals restrict themselves to a
    /// shape by this name -- see Model::decals.
    const std::string& shape_name() const noexcept { return shape_name_; }
    void set_shape_name(std::string name) { shape_name_ = std::move(name); }

    /// Per-mesh hull-decal enable mask: bit i => Model::decals[i] may paint
    /// this mesh. Defaults to all four bits; build_model clears bit i on
    /// every mesh whose shape_name() differs from decal i's `shape` (when
    /// that decal names one). The renderer ANDs it with the list size.
    std::uint8_t decal_mask() const noexcept { return decal_mask_; }
    void set_decal_mask(std::uint8_t mask) noexcept { decal_mask_ = mask; }

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
    std::string shape_name_;
    std::uint8_t decal_mask_ = 0x0F;
    std::optional<MeshCpu> cpu_data_;
    std::vector<Mesh> lod_chain_;
};

/// Upload a CPU-side mesh to a GL VAO/VBO/EBO triple. Public so the
/// renderer can build its own meshes (e.g. backdrop spheres) without
/// going through the model-build pipeline.
Mesh upload_mesh(const MeshCpu& cpu);

}  // namespace assets
