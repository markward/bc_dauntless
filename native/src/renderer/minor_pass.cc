// native/src/renderer/minor_pass.cc
// Minor rocks (docs/superpowers/specs/2026-10-01-minor-rocks-design.md, §2).
#include "renderer/minor_pass.h"

#include <cstddef>
#include <cstdint>
#include <cstdio>

#include <glad/glad.h>

#include <glm/glm.hpp>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>

#include <scenegraph/camera.h>

#include "renderer/frame.h"
#include "renderer/pipeline.h"
#include "renderer/shader.h"

// Defined in frame.cc (global namespace), read the way draw_model reads them.
namespace dauntless_nan_debug { bool enabled(); }
namespace dauntless_normal_map {
    bool  enabled();
    float strength();
    bool  flip_green();
}

namespace renderer {
namespace {

static_assert(sizeof(minors::InstanceGpu) == 3 * 4 * sizeof(float),
              "InstanceGpu must be three tightly packed vec4 rows");
constexpr GLsizei kInstanceStride = static_cast<GLsizei>(sizeof(minors::InstanceGpu));
constexpr GLuint  kRow0Attrib = 7;     // minor.vert a_row0..a_row2 = 7..9

GLuint make_1x1(const std::uint8_t rgba[4]) {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return t;
}

int stage_texture(const assets::Material& mat, assets::Material::StageSlot slot) {
    return mat.stages[static_cast<std::size_t>(slot)].texture_index;
}

}  // namespace

MinorPass::~MinorPass() {
    forget_models();
    if (instance_vbo_ != 0) { GLuint b = instance_vbo_; glDeleteBuffers(1, &b); }
    if (white_texture_ != 0) { GLuint t = white_texture_; glDeleteTextures(1, &t); }
    if (black_texture_ != 0) { GLuint t = black_texture_; glDeleteTextures(1, &t); }
}

void MinorPass::forget_models() {
    for (auto& [key, vao] : vaos_) {
        (void)key;
        GLuint v = vao;
        glDeleteVertexArrays(1, &v);
    }
    vaos_.clear();
}

std::uint32_t MinorPass::ensure_white_texture() {
    if (white_texture_ == 0) {
        const std::uint8_t white[4] = {255, 255, 255, 255};
        white_texture_ = make_1x1(white);
    }
    return white_texture_;
}

std::uint32_t MinorPass::ensure_black_texture() {
    if (black_texture_ == 0) {
        const std::uint8_t black[4] = {0, 0, 0, 255};
        black_texture_ = make_1x1(black);
    }
    return black_texture_;
}

std::uint32_t MinorPass::vao_for(std::uint64_t handle, int mesh_index, std::uint32_t vbo,
                                 std::uint32_t ebo) {
    const auto key = std::make_pair(handle, mesh_index);
    if (auto it = vaos_.find(key); it != vaos_.end()) return it->second;

    GLuint vao = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    // Attributes 0/1/2 exactly as assets/src/mesh_upload.cc lays them out.
    using V = assets::MeshCpu::Vertex;
    const GLsizei stride = sizeof(V);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, position)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, normal)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, uv)));
    // Rows 7/8/9 from the shared instance buffer, one per instance. The
    // offset is re-pointed per bin in render().
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    for (GLuint k = 0; k < 3; ++k) {
        glEnableVertexAttribArray(kRow0Attrib + k);
        glVertexAttribPointer(kRow0Attrib + k, 4, GL_FLOAT, GL_FALSE, kInstanceStride,
                              reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
        glVertexAttribDivisor(kRow0Attrib + k, 1);
    }
    vaos_.emplace(key, vao);
    return vao;
}

void MinorPass::render(const minors::MinorField& field, const scenegraph::Camera& cam,
                       Pipeline& pipeline,
                       const std::function<const assets::Model*(std::uint64_t)>& lookup,
                       const Lighting& lighting, float ambient_scale, float rim_strength) {
    draw_calls_ = 0;
    const auto& bins = field.bins();
    if (bins.empty()) return;

    // 1-2. Per-frame uniforms, exactly as submit_opaque_in_pass's configure_common.
    Shader& s = pipeline.minor_shader();
    s.use();
    s.set_mat4("u_view", cam.view_matrix());
    s.set_mat4("u_proj", cam.proj_matrix());
    s.set_vec3("u_camera_pos_ws", glm::vec3(glm::inverse(cam.view_matrix())[3]));
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }

    // 3. Every per-instance feature of the opaque path is off for minors.
    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();
    s.set_int("u_decal_count", 0);
    s.set_int("u_glow_region_count", 0);
    s.set_int("u_dyn_light_count", 0);
    s.set_int("u_carve_enabled", 0);
    s.set_int("u_carve_count", 0);
    s.set_int("u_carve_invert", 0);
    s.set_int("u_hull_field", 6);
    s.set_int("u_hull_field_enabled", 0);
    s.set_int("u_frame_enabled", 0);
    s.set_int("u_damage_decal", 3);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, black);
    s.set_int("u_hull_decal_count", 0);
    s.set_int("u_decal_enabled_mask", 0);
    s.set_mat4("u_node_rest_fix", glm::mat4(1.0f));
    s.set_float("u_emissive_scale", 1.0f);
    glActiveTexture(GL_TEXTURE7);
    glBindTexture(GL_TEXTURE_2D, 0);       // draw_model's undamaged scuff binding
    s.set_int("u_scuff_map_ok", 0);
    s.set_int("u_nan_debug", dauntless_nan_debug::enabled() ? 1 : 0);
    s.set_float("u_rim_strength", rim_strength);
    s.set_mat4("u_model", glm::mat4(1.0f));    // unused by minor.vert; never stale
    {
        // Sun shadow, as draw_model binds it (unit 5).
        const bool shadows_on = active_shadow_enabled();
        const int unit = 5;
        s.set_int("u_shadows_enabled", shadows_on ? 1 : 0);
        s.set_int("u_shadow_map", unit);
        if (shadows_on) {
            const ShadowLight& light = active_shadow_light();
            s.set_mat4("u_light_view_proj", light.view_proj);
            s.set_float("u_shadow_texel", light.texel_world_size);
            glActiveTexture(GL_TEXTURE0 + unit);
            glBindTexture(GL_TEXTURE_2D, active_shadow_texture());
        }
    }
    glActiveTexture(GL_TEXTURE0);

    // 4. Every bin's instances into one stream buffer, bin after bin.
    staging_.clear();
    std::vector<std::size_t> bin_offset(bins.size());
    for (std::size_t b = 0; b < bins.size(); ++b) {
        bin_offset[b] = staging_.size() * sizeof(minors::InstanceGpu);
        staging_.insert(staging_.end(), bins[b].items.begin(), bins[b].items.end());
    }
    if (instance_vbo_ == 0) {
        GLuint buf = 0;
        glGenBuffers(1, &buf);
        instance_vbo_ = buf;
    }
    const std::size_t bytes = staging_.size() * sizeof(minors::InstanceGpu);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    if (bytes > instance_capacity_) instance_capacity_ = bytes;   // grows only
    // Orphan, then fill: the driver need not wait on last frame's draws.
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(instance_capacity_), nullptr,
                 GL_STREAM_DRAW);
    glBufferSubData(GL_ARRAY_BUFFER, 0, static_cast<GLsizeiptr>(bytes), staging_.data());

    // 5. One instanced draw per bin.
    for (std::size_t b = 0; b < bins.size(); ++b) {
        const minors::Bin& bin = bins[b];
        if (bin.items.empty()) continue;
        const auto& frags = field.fragments(bin.family);
        if (bin.slot < 0 || static_cast<std::size_t>(bin.slot) >= frags.size()) continue;
        const minors::Fragment& f = frags[static_cast<std::size_t>(bin.slot)];
        const std::uint64_t handle = bin.lod == 0 ? f.lod0 : f.lod1;
        const assets::Model* model = lookup(handle);
        if (model == nullptr) continue;

        // The first node carrying a mesh, and its first mesh. Catalogue
        // fragments are one node holding one mesh at the identity; anything
        // else draws only that mesh, unposed by its node -- say so once.
        const assets::Node* node = nullptr;
        for (const auto& n : model->nodes)
            if (!n.meshes.empty()) { node = &n; break; }
        if (node == nullptr) continue;
        if (!warned_shape_ && (model->nodes.size() != 1 || node->meshes.size() != 1 ||
                               node->local_transform != glm::mat4(1.0f))) {
            warned_shape_ = true;
            std::fprintf(stderr,
                         "[minor_pass] fragment model %llu is not one identity node "
                         "with one mesh (%zu nodes, %zu meshes); drawing its first mesh\n",
                         static_cast<unsigned long long>(handle), model->nodes.size(),
                         node->meshes.size());
        }
        const int mesh_index = node->meshes.front();
        const assets::Mesh& mesh = model->meshes[static_cast<std::size_t>(mesh_index)];

        glBindVertexArray(vao_for(handle, mesh_index, mesh.vbo(), mesh.ebo()));
        glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
        for (GLuint k = 0; k < 3; ++k) {
            glVertexAttribPointer(
                kRow0Attrib + k, 4, GL_FLOAT, GL_FALSE, kInstanceStride,
                reinterpret_cast<void*>(static_cast<std::uintptr_t>(bin_offset[b] + k * 16)));
        }

        // Material, as draw_model's mesh loop sets it.
        const assets::Material mat = mesh.material_index() >= 0
            ? model->materials[static_cast<std::size_t>(mesh.material_index())]
            : assets::Material{};
        s.set_vec3("u_diffuse_color", mat.diffuse);
        s.set_vec3("u_emissive_color", mat.emissive);

        const int base_tex = stage_texture(mat, assets::Material::StageSlot::Base);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D,
                      base_tex >= 0 ? model->textures[static_cast<std::size_t>(base_tex)].id()
                                    : white);
        s.set_int("u_base_color", 0);

        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, black);
        s.set_int("u_glow_map", 1);

        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, black);
        s.set_int("u_specular_map", 2);
        s.set_int("u_specular_enabled", 0);

        const int bump_tex = stage_texture(mat, assets::Material::StageSlot::Bump);
        glActiveTexture(GL_TEXTURE4);
        glBindTexture(GL_TEXTURE_2D,
                      bump_tex >= 0 ? model->textures[static_cast<std::size_t>(bump_tex)].id()
                                    : black);
        glActiveTexture(GL_TEXTURE0);
        s.set_int("u_normal_map", 4);
        s.set_int("u_normal_enabled",
                  (bump_tex >= 0 && dauntless_normal_map::enabled()) ? 1 : 0);
        s.set_float("u_normal_strength", dauntless_normal_map::strength());
        s.set_int("u_normal_flip_g", dauntless_normal_map::flip_green() ? 1 : 0);

        glDrawElementsInstanced(GL_TRIANGLES, static_cast<GLsizei>(mesh.index_count()),
                                GL_UNSIGNED_INT, nullptr,
                                static_cast<GLsizei>(bin.items.size()));
        ++draw_calls_;
    }

    // 6. Leave no VAO bound and unit 0 active.
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glActiveTexture(GL_TEXTURE0);
}

}  // namespace renderer
