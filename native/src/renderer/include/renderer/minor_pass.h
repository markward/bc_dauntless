// native/src/renderer/include/renderer/minor_pass.h
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md, §2):
// the instanced draw of MinorField::bins(). One glDrawElementsInstanced per
// non-empty bin, through Pipeline::minor_shader() -- minor.vert linked with the
// EXISTING opaque.frag -- so a minor is lit exactly as a major is.
#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <utility>
#include <vector>

#include <renderer/minor_field.h>

namespace assets { struct Model; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct Lighting;

class MinorPass {
public:
    MinorPass() = default;
    MinorPass(const MinorPass&) = delete;
    MinorPass& operator=(const MinorPass&) = delete;
    ~MinorPass();                       // deletes VAOs / instance VBO (GL alive)

    // Draws field.bins() into the bound target. `lookup` resolves a model handle.
    void render(const minors::MinorField& field, const scenegraph::Camera& cam,
                Pipeline& pipeline,
                const std::function<const assets::Model*(std::uint64_t)>& lookup,
                const Lighting& lighting, float ambient_scale, float rim_strength);

    // Drop VAOs keyed on model handles (mission swap: handles are recycled).
    void forget_models();

    int last_draw_calls() const { return draw_calls_; }

private:
    std::uint32_t ensure_white_texture();
    std::uint32_t ensure_black_texture();
    // The VAO for (model handle, mesh index): the mesh's own vbo/ebo on
    // attributes 0..2 plus the shared instance buffer on 7..9. Never the
    // mesh's own VAO, which the opaque path still owns unmodified.
    std::uint32_t vao_for(std::uint64_t handle, int mesh_index, std::uint32_t vbo,
                          std::uint32_t ebo);

    std::map<std::pair<std::uint64_t, int>, std::uint32_t> vaos_;
    std::uint32_t instance_vbo_ = 0;
    std::size_t   instance_capacity_ = 0;      // bytes
    std::vector<minors::InstanceGpu> staging_;
    std::uint32_t white_texture_ = 0;
    std::uint32_t black_texture_ = 0;
    int draw_calls_ = 0;
    bool warned_shape_ = false;
};

}  // namespace renderer
