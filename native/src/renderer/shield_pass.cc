// native/src/renderer/shield_pass.cc
#include "renderer/shield_pass.h"

#include "renderer/pipeline.h"
#include "sphere_mesh.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <cstdio>
#include <fstream>

namespace renderer {

ShieldPass::ShieldPass() = default;
ShieldPass::~ShieldPass() = default;

void ShieldPass::register_ship(scenegraph::InstanceId id,
                                ShieldMode mode,
                                float decay_seconds,
                                const glm::vec4& default_color,
                                const glm::vec3& aabb_center,
                                const glm::vec3& aabb_half_extents) {
    registry_.register_instance(id, mode, decay_seconds, default_color,
                                aabb_center, aabb_half_extents);
}

void ShieldPass::unregister_ship(scenegraph::InstanceId id) {
    registry_.unregister_instance(id);
}

void ShieldPass::shield_hit(scenegraph::InstanceId id,
                             const glm::vec3& point_world,
                             const glm::vec4& rgba,
                             float intensity,
                             double now_seconds) {
    registry_.push_hit(id, point_world, rgba, intensity, now_seconds);
}

assets::Mesh* ShieldPass::ensure_sphere() {
    if (sphere_) return sphere_.get();
    assets::MeshCpu cpu = build_uv_sphere(256);
    sphere_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
    return sphere_.get();
}

void ShieldPass::ensure_textures_loaded() {
    if (tex_loaded_) return;
    for (int i = 0; i < 4; ++i) {
        char path[256];
        std::snprintf(path, sizeof(path),
                      "game/data/Textures/Tactical/shieldhit0%d.TGA", i + 1);
        std::ifstream in(path, std::ios::binary);
        if (!in) {
            std::fprintf(stderr, "[shield] failed to open '%s'\n", path);
            tex_[i] = std::make_unique<assets::Texture>();
            continue;
        }
        in.seekg(0, std::ios::end);
        auto size = static_cast<std::size_t>(in.tellg());
        in.seekg(0, std::ios::beg);
        std::vector<std::uint8_t> bytes(size);
        in.read(reinterpret_cast<char*>(bytes.data()),
                static_cast<std::streamsize>(size));
        try {
            assets::Image img = assets::decode_tga(bytes);
            assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
            tex_[i] = std::make_unique<assets::Texture>(std::move(tex));
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[shield] failed to decode '%s': %s\n", path, e.what());
            tex_[i] = std::make_unique<assets::Texture>();
        }
    }
    tex_loaded_ = true;
}

void ShieldPass::submit(const scenegraph::World& world,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline,
                         double now_seconds) {
    registry_.tick_all(now_seconds);

    // Early-out before any GL state setup if nothing to draw.
    bool any_active = false;
    for (const auto& [id, state] : registry_) {
        if (state.active_count() > 0) { any_active = true; break; }
    }
    if (!any_active) return;

    assets::Mesh* sphere = ensure_sphere();
    if (!sphere) return;
    ensure_textures_loaded();

    auto& shader = pipeline.shield_shader();
    shader.use();
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_mat4("u_view", camera.view_matrix());

    // Alpha-weighted additive: src*src_alpha + dest. Depth test on, depth
    // write off — fading flashes shouldn't occlude later passes.
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glDepthMask(GL_FALSE);

    // Bind four shieldhit textures to units 0..3 once; sampler uniforms set
    // once per submit. The shader picks via u_hit_tex_index per slot.
    for (int i = 0; i < 4; ++i) {
        glActiveTexture(GL_TEXTURE0 + i);
        glBindTexture(GL_TEXTURE_2D, tex_[i] ? tex_[i]->id() : 0);
    }
    shader.set_int("u_shieldhit_0", 0);
    shader.set_int("u_shieldhit_1", 1);
    shader.set_int("u_shieldhit_2", 2);
    shader.set_int("u_shieldhit_3", 3);
    shader.set_float("u_hex_tile_rate", 1.0f / 5.0f);  // 1 hex per 5 m

    glBindVertexArray(sphere->vao());

    for (const auto& [id, state] : registry_) {
        if (state.active_count() == 0) continue;
        if (state.mode != ShieldMode::Ellipsoid) continue;  // skin = Task 15

        const auto* inst = world.get(id);
        if (!inst || !inst->visible) continue;

        const glm::mat4 ship_local =
            glm::translate(glm::mat4(1.0f), state.aabb_center)
            * glm::scale(glm::mat4(1.0f), state.aabb_half_extents * 1.1f);
        shader.set_mat4("u_world", inst->world);
        shader.set_mat4("u_ship_local", ship_local);

        glm::vec4 pts[ShieldState::MaxHits];
        glm::vec4 col[ShieldState::MaxHits];
        int       tex_idx[ShieldState::MaxHits];
        for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
            const auto& h = state.slot(i);
            pts[i]     = glm::vec4(h.point_world, 0.0f);
            col[i]     = glm::vec4(glm::vec3(h.color_rgba), h.current_intensity);
            tex_idx[i] = h.texture_index;
        }
        shader.set_vec4_array("u_hit_points", pts, ShieldState::MaxHits);
        shader.set_vec4_array("u_hit_color_intensity", col, ShieldState::MaxHits);
        shader.set_int_array("u_hit_tex_index", tex_idx, ShieldState::MaxHits);

        const float largest_axis = std::max({state.aabb_half_extents.x,
                                              state.aabb_half_extents.y,
                                              state.aabb_half_extents.z});
        shader.set_float("u_hit_radius", largest_axis * 0.25f);

        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glBindVertexArray(0);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
