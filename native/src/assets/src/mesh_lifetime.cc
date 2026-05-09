#include <assets/mesh.h>

#include <utility>

namespace assets {

Mesh::Mesh(GLuint vao, GLuint vbo, GLuint ebo,
           std::uint32_t index_count, int material_index, int node_index) noexcept
    : vao_(vao), vbo_(vbo), ebo_(ebo)
    , index_count_(index_count)
    , material_index_(material_index), node_index_(node_index) {}

Mesh::Mesh(Mesh&& o) noexcept
    : vao_(std::exchange(o.vao_, 0))
    , vbo_(std::exchange(o.vbo_, 0))
    , ebo_(std::exchange(o.ebo_, 0))
    , index_count_(std::exchange(o.index_count_, 0))
    , material_index_(std::exchange(o.material_index_, -1))
    , node_index_(std::exchange(o.node_index_, -1))
    , cpu_data_(std::move(o.cpu_data_))
    , lod_chain_(std::move(o.lod_chain_)) {}

Mesh& Mesh::operator=(Mesh&& o) noexcept {
    if (this != &o) {
        if (vao_) glDeleteVertexArrays(1, &vao_);
        if (vbo_) glDeleteBuffers(1, &vbo_);
        if (ebo_) glDeleteBuffers(1, &ebo_);
        vao_            = std::exchange(o.vao_, 0);
        vbo_            = std::exchange(o.vbo_, 0);
        ebo_            = std::exchange(o.ebo_, 0);
        index_count_    = std::exchange(o.index_count_, 0);
        material_index_ = std::exchange(o.material_index_, -1);
        node_index_     = std::exchange(o.node_index_, -1);
        cpu_data_       = std::move(o.cpu_data_);
        lod_chain_      = std::move(o.lod_chain_);
    }
    return *this;
}

Mesh::~Mesh() {
    if (vao_) glDeleteVertexArrays(1, &vao_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (ebo_) glDeleteBuffers(1, &ebo_);
}

}  // namespace assets
