// native/src/renderer/shield_pass.cc
#include "renderer/shield_pass.h"

#include "renderer/pipeline.h"
#include "renderer/skin_shield.h"
#include "sphere_mesh.h"

#include <assets/model.h>
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
    // 4096 tris (32 lat × 64 lon) — smooth silhouette at typical
    // bubble screen sizes; the sphere is reused across every
    // ellipsoid-mode ship so the one-time build cost is amortized.
    assets::MeshCpu cpu = build_uv_sphere(4096);
    sphere_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
    return sphere_.get();
}

assets::Mesh* ShieldPass::ensure_skin_mesh(scenegraph::ModelHandle handle,
                                            const assets::Model& model,
                                            float inflate_distance) {
    auto it = skin_cache_.find(handle);
    if (it != skin_cache_.end()) return it->second.get();
    assets::MeshCpu cpu = build_skin_shield_meshcpu(model, inflate_distance);
    if (cpu.vertices.empty() || cpu.indices.empty()) {
        // Cache an empty placeholder so we don't retry every frame for a
        // model that has no CPU-side data.
        skin_cache_[handle] = std::make_unique<assets::Mesh>();
        return nullptr;
    }
    auto owned = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
    auto* raw = owned.get();
    skin_cache_[handle] = std::move(owned);
    return raw;
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
                         double now_seconds,
                         const ModelLookup& model_lookup) {
    registry_.tick_all(now_seconds);

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

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glDepthMask(GL_FALSE);
    // Ship world matrices negate the X column to satisfy glFrontFace(GL_CW)
    // for hull rendering (see d1ac130). That flip inverts our sphere/skin
    // winding, so back-face culling would kill every fragment. Disable
    // culling for the additive bubble — both faces should be visible
    // through each other anyway.
    glDisable(GL_CULL_FACE);

    for (int i = 0; i < 4; ++i) {
        glActiveTexture(GL_TEXTURE0 + i);
        glBindTexture(GL_TEXTURE_2D, tex_[i] ? tex_[i]->id() : 0);
    }
    shader.set_int("u_shieldhit_0", 0);
    shader.set_int("u_shieldhit_1", 1);
    shader.set_int("u_shieldhit_2", 2);
    shader.set_int("u_shieldhit_3", 3);

    for (const auto& [id, state] : registry_) {
        if (state.active_count() == 0) continue;

        const auto* inst = world.get(id);
        if (!inst || !inst->visible) continue;

        // Pick mesh + ship_local matrix per mode.
        assets::Mesh* mesh = nullptr;
        glm::mat4 ship_local{1.0f};
        if (state.mode == ShieldMode::Skin && model_lookup) {
            const assets::Model* model = model_lookup(inst->model_handle);
            if (model) {
                const float largest_axis =
                    std::max({state.aabb_half_extents.x,
                              state.aabb_half_extents.y,
                              state.aabb_half_extents.z});
                mesh = ensure_skin_mesh(inst->model_handle, *model,
                                         largest_axis * 0.05f);
            }
            // ship_local stays identity: skin verts already in ship-local
            // (post-inflate) coordinates.
        }
        if (mesh == nullptr) {
            // Ellipsoid path: either mode=Ellipsoid, or skin build failed.
            // 1.32× padding (1.1 base × 1.2 user-requested bump) so the
            // bubble clears the hull on ships whose AABB walks miss
            // orphan meshes or whose NIF geometry sits asymmetric to its
            // pivot point.
            mesh = sphere;
            ship_local = glm::translate(glm::mat4(1.0f), state.aabb_center)
                       * glm::scale(glm::mat4(1.0f),
                                     state.aabb_half_extents * 1.32f);
        }

        shader.set_mat4("u_world", inst->world);
        shader.set_mat4("u_ship_local", ship_local);
        // World-space ship center for the impact-centered splash UV in
        // the fragment shader. inst->world's column 3 holds translation.
        shader.set_vec3("u_ship_center", glm::vec3(inst->world[3]));

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
        // aabb_half_extents is in NIF units; the ship's world matrix
        // applies a uniform scale (SHIP_SCALE on the host side). Recover
        // it from the column length so hit_radius lands in world units
        // (matching v_world_pos and hit_point.xyz the shader compares
        // against). Without this the radius is ~10× too large and the
        // hex pattern bleeds across the entire ellipsoid.
        const float scale_factor = glm::length(glm::vec3(inst->world[0]));
        // 0.6 = larger splash for visual debug; tune down later once the
        // bubble silhouette is verified to clear the hull. With 0.25 the
        // flash only covered ~quarter of the bubble surface and made it
        // hard to see whether the ship was clipping out.
        shader.set_float("u_hit_radius", largest_axis * scale_factor * 1.5f);

        glBindVertexArray(mesh->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(mesh->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
