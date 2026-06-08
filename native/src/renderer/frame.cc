// native/src/renderer/frame.cc
#include "renderer/frame.h"
#include "renderer/lighting.h"
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/damage_decals.h>

#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>
#include <assets/material.h>

#include <glm/gtc/matrix_transform.hpp>

#include <vector>

// Toggle for the opaque-pass specular term. Default on so existing
// renders look identical until the user flips the Configuration row.
// host_bindings.cc calls set_enabled(); frame.cc reads enabled() when
// binding the opaque shader and writes u_specular_enabled.
namespace dauntless_specular {
namespace {
    bool g_specular_enabled = true;
}
    bool enabled() { return g_specular_enabled; }
    void set_enabled(bool v) { g_specular_enabled = v; }
}

// Toggle for the opaque-pass Fresnel rim term. Default on so the
// "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; frame.cc reads enabled() per draw when binding the
// opaque shader's u_rim_strength.
namespace dauntless_rim {
namespace {
    bool g_rim_enabled = true;
}
    bool enabled() { return g_rim_enabled; }
    void set_enabled(bool v) { g_rim_enabled = v; }
}

// Toggle for the HDR resolve pass (tonemap + bloom + grade). Default on.
// host_bindings.cc forward-declares set_enabled; frame() reads enabled()
// when calling g_resolve_pass->set_hdr_enabled().
namespace dauntless_hdr {
namespace {
    bool g_hdr_enabled = true;
}
    bool enabled() { return g_hdr_enabled; }
    void set_enabled(bool v) { g_hdr_enabled = v; }
}

// Toggle for the opaque-pass persistent damage decals (Phase 2). Default on
// so the "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; draw_model reads enabled() per instance and uploads
// u_decal_count = 0 when off (stock-BC hull, no per-fragment decal cost).
namespace dauntless_decals {
namespace {
    bool g_decals_enabled = true;
}
    bool enabled() { return g_decals_enabled; }
    void set_enabled(bool v) { g_decals_enabled = v; }
}

namespace renderer {

namespace {

void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                GLuint white_fallback,
                GLuint black_fallback,
                bool rim_active,
                const scenegraph::DamageDecalRing& decals,
                float decal_time) {
    // ── Per-instance damage decals (Phase 2) ───────────────────────────────
    // Pack the active ring into vec4 arrays. point_body is in NIF/model units
    // (the ship scale lives in `world`), so convert radius GU->model units via
    // the world-matrix scale s = |world's X column|. u_decal_count == 0 when
    // disabled or empty makes the shader skip the loop entirely.
    {
        glm::vec4 a[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 b[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 c[scenegraph::DamageDecalRing::kMaxDecals];
        int n = 0;
        if (dauntless_decals::enabled()) {
            const float s = glm::length(glm::vec3(world[0]));   // uniform scale
            const float inv_s = (s > 0.0f) ? (1.0f / s) : 1.0f;
            for (const auto& d : decals.slots()) {
                if (!d.active) continue;
                a[n] = glm::vec4(d.point_body, d.intensity);
                b[n] = glm::vec4(d.normal_body, d.radius * inv_s);  // GU->model
                c[n] = glm::vec4(d.birth_time,
                                 static_cast<float>(static_cast<std::uint32_t>(d.weapon_class)),
                                 0.0f, 0.0f);
                ++n;
            }
        }
        shader.set_int("u_decal_count", n);
        if (n > 0) {
            shader.set_vec4_array("u_decal_a", a, n);
            shader.set_vec4_array("u_decal_b", b, n);
            shader.set_vec4_array("u_decal_c", c, n);
            // world->body for in-shader body-frame reconstruction. The opaque
            // shader's location is -1 until the Phase 2 decal shader lands;
            // needed then, so this is not dead code.
            shader.set_mat4("u_ship_world_inv", glm::inverse(world));
            shader.set_float("u_decal_time", decal_time);
        }
    }

    // Walk nodes; each node may reference one or more meshes by index. The
    // node's local_transform is composed with parent transforms here. The
    // asset pipeline already orders nodes such that parents precede children,
    // so a single linear pass suffices.
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = world * model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            shader.set_mat4("u_model", world_per_node[i]);

            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            shader.set_vec3("u_diffuse_color", mat.diffuse);
            shader.set_vec3("u_emissive_color", mat.emissive);

            const int base_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Base)
            ].texture_index;
            glActiveTexture(GL_TEXTURE0);
            if (base_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, white_fallback);
            }
            shader.set_int("u_base_color", 0);

            const int glow_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Glow)
            ].texture_index;
            glActiveTexture(GL_TEXTURE1);
            if (glow_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[glow_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            shader.set_int("u_glow_map", 1);

            // Opaque-pass texture-unit convention: 0 = base, 1 = glow,
            // 2 = specular mask. Each unit owns one sampler uniform.
            //
            // Spec contribution is gated on presence of a _specular/_spec
            // texture: missing -> black_fallback -> spec term multiplies
            // to zero -> ship renders identically to today. This is
            // intentional (see specular-rendering-design.md "Scope
            // decision"). Stock BC ships all author non-zero
            // NiMaterialProperty.specular/glossiness; flipping the
            // fallback to white_fallback would shift the visual baseline
            // of every existing ship in one change.
            const int spec_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Gloss)
            ].texture_index;
            glActiveTexture(GL_TEXTURE2);
            if (spec_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[spec_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            shader.set_int  ("u_specular_map",   2);
            shader.set_vec3 ("u_specular_color", mat.specular);
            shader.set_float("u_specular_power",
                renderer::glossiness_to_specular_power(mat.glossiness));
            shader.set_int("u_specular_enabled",
                           dauntless_specular::enabled() ? 1 : 0);
            const float rim = rim_active
                ? renderer::rim_strength_from_material(mat.specular, mat.glossiness)
                : 0.0f;
            shader.set_float("u_rim_strength", rim);

            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}

}  // namespace

FrameSubmitter::~FrameSubmitter() {
    if (white_texture_ != 0) {
        GLuint t = white_texture_;
        glDeleteTextures(1, &t);
        white_texture_ = 0;
    }
    if (black_texture_ != 0) {
        GLuint t = black_texture_;
        glDeleteTextures(1, &t);
        black_texture_ = 0;
    }
}

std::uint32_t FrameSubmitter::ensure_white_texture() {
    if (white_texture_ != 0) return white_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t white[4] = {255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    white_texture_ = t;
    return white_texture_;
}

std::uint32_t FrameSubmitter::ensure_black_texture() {
    if (black_texture_ != 0) return black_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t black[4] = {0, 0, 0, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, black);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    black_texture_ = t;
    return black_texture_;
}

void FrameSubmitter::submit_opaque(const scenegraph::World& world,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline,
                                   const ModelLookup& lookup,
                                   const Lighting& lighting,
                                   float decal_time) {
    auto& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    const glm::vec3 cam_pos_ws =
        glm::vec3(glm::inverse(camera.view_matrix())[3]);
    shader.set_vec3("u_camera_pos_ws", cam_pos_ws);

    shader.set_vec3("u_ambient_light", lighting.ambient);
    shader.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        shader.set_vec3_array("u_dir_light_dir_ws",
                              lighting.directional_dir_ws,
                              lighting.directional_count);
        shader.set_vec3_array("u_dir_light_color",
                              lighting.directional_color,
                              lighting.directional_count);
    }

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        const bool rim_active = dauntless_rim::enabled() && inst.rim_eligible;
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active,
                          inst.decals, decal_time);
    });
}

void FrameSubmitter::submit_opaque_in_pass(const scenegraph::World& world,
                                           const scenegraph::Camera& camera,
                                           Pipeline& pipeline,
                                           const ModelLookup& lookup,
                                           const Lighting& lighting,
                                           scenegraph::Pass pass,
                                           float decal_time) {
    auto& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    const glm::vec3 cam_pos_ws =
        glm::vec3(glm::inverse(camera.view_matrix())[3]);
    shader.set_vec3("u_camera_pos_ws", cam_pos_ws);

    shader.set_vec3("u_ambient_light", lighting.ambient);
    shader.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        shader.set_vec3_array("u_dir_light_dir_ws",
                              lighting.directional_dir_ws,
                              lighting.directional_count);
        shader.set_vec3_array("u_dir_light_color",
                              lighting.directional_color,
                              lighting.directional_count);
    }

    const GLuint white = ensure_white_texture();
    const GLuint black = ensure_black_texture();

    world.for_each_visible_in_pass(pass, [&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        const bool rim_active = dauntless_rim::enabled() && inst.rim_eligible;
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active,
                          inst.decals, decal_time);
    });
}

}  // namespace renderer
