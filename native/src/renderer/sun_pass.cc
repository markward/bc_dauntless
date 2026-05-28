// native/src/renderer/sun_pass.cc
#include "renderer/sun_pass.h"

#include "renderer/pipeline.h"
#include "sphere_mesh.h"

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>

namespace renderer {

SunPass::~SunPass() {
    // assets::Mesh / assets::Texture destructors release GL handles.
    // Caller must ensure the GL context is still alive when this dtor runs.
    if (flare_quad_vbo_) glDeleteBuffers(1, &flare_quad_vbo_);
    if (flare_quad_vao_) glDeleteVertexArrays(1, &flare_quad_vao_);
}

assets::Mesh* SunPass::ensure_sphere(int target_tris) {
    if (target_tris < 64) target_tris = 64;
    auto it = sphere_cache_.find(target_tris);
    if (it != sphere_cache_.end()) return it->second.get();
    assets::MeshCpu cpu = build_uv_sphere(target_tris);
    assets::Mesh m = assets::upload_mesh(cpu);
    auto owned = std::make_unique<assets::Mesh>(std::move(m));
    auto* raw = owned.get();
    sphere_cache_.emplace(target_tris, std::move(owned));
    return raw;
}

assets::Texture* SunPass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[sun] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
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
        auto owned = std::make_unique<assets::Texture>(std::move(tex));
        auto* raw = owned.get();
        texture_cache_.emplace(path, std::move(owned));
        return raw;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[sun] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

void SunPass::ensure_flare_quad() {
    if (flare_quad_vao_ != 0) return;
    constexpr float kCorners[8] = {
        -1.0f, -1.0f,
         1.0f, -1.0f,
        -1.0f,  1.0f,
         1.0f,  1.0f,
    };
    glGenVertexArrays(1, &flare_quad_vao_);
    glBindVertexArray(flare_quad_vao_);
    glGenBuffers(1, &flare_quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, flare_quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kCorners), kCorners, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(float) * 2, nullptr);
    glEnableVertexAttribArray(0);
    glBindVertexArray(0);
}

void SunPass::render(const std::vector<SunDescriptor>& suns,
                     const scenegraph::Camera& camera,
                     Pipeline& pipeline,
                     double now_seconds) {
    if (suns.empty()) return;

    auto& shader = pipeline.sun_shader();
    shader.use();
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_mat4("u_view", camera.view_matrix());

    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
    glCullFace(GL_FRONT);   // render inside of sphere

    assets::Mesh* sphere = ensure_sphere(256);
    if (!sphere) {
        glCullFace(GL_BACK);
        return;
    }
    glBindVertexArray(sphere->vao());

    // Suns in BC sit tens of km from the origin (e.g. 63km), but BC's
    // captured frustum has far=5000. Match that by remapping each sun
    // along its camera-direction to sit just inside the far plane,
    // shrinking the radius by the same factor so the angular size is
    // preserved.
    const float virtual_distance = camera.far * 0.95f;
    // The aggregator passes corona_radius = body_radius * 1.1, so the
    // sphere shell sits as a thin halo just outside the body. The flare
    // particle system (drawn below) provides the wispy arcing-plasma
    // detail that BC's SunEffect node renders.
    constexpr int   kFlareGridSize         = 8;       // sprite atlas grid
    constexpr int   kFlareParticleCount    = 16;      // puffs per sun per frame
    constexpr float kFlareLifetimeSec      = 1.2f;    // per-puff birth-to-death
    constexpr float kFlareParticleMinScale = 0.15f;   // ×body_radius
    constexpr float kFlareParticleMaxScale = 0.30f;   // ×body_radius

    for (const auto& s : suns) {
        assets::Texture* tex = ensure_texture(s.base_texture_path);
        if (!tex) continue;

        const glm::vec3 cam_to_sun = s.position - camera.eye;
        const float true_distance = glm::length(cam_to_sun);
        if (true_distance < 1e-3f) continue;
        const float scale_factor = virtual_distance / true_distance;
        const glm::vec3 virtual_pos =
            camera.eye + (cam_to_sun / true_distance) * virtual_distance;
        const float virtual_radius = s.radius        * scale_factor;
        const float virtual_corona = s.corona_radius * scale_factor;

        // Body: opaque sphere scaled to virtual_radius at virtual_pos
        glm::mat4 model = glm::translate(glm::mat4(1.0f), virtual_pos)
                        * glm::scale(glm::mat4(1.0f), glm::vec3(virtual_radius));
        shader.set_mat4("u_model", model);
        shader.set_int("u_corona", 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_int("u_texture", 0);
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);

        // Corona: additive semi-transparent shell — depth writes off so the
        // halo doesn't occlude opaque geometry behind it.
        if (virtual_corona > virtual_radius) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            glDepthMask(GL_FALSE);
            glm::mat4 corona_model =
                glm::translate(glm::mat4(1.0f), virtual_pos)
                * glm::scale(glm::mat4(1.0f), glm::vec3(virtual_corona));
            shader.set_mat4("u_model", corona_model);
            shader.set_int("u_corona", 1);
            glDrawElements(GL_TRIANGLES,
                           static_cast<GLsizei>(sphere->index_count()),
                           GL_UNSIGNED_INT, nullptr);
            glDepthMask(GL_TRUE);
            glDisable(GL_BLEND);
        }

        // Flare overlay: BC SunEffect-style plasma-puff particle system.
        // The SunFlares*.tga textures are 8x8 grids of distinct plasma
        // puffs (NOT sequential frames of one animation). We render N
        // short-lived camera-facing billboards anchored to random points
        // on the sphere's surface; each particle picks a sprite cell at
        // birth and fades through a sin() envelope over its lifetime,
        // then respawns at a new sphere position with a new cell.
        // Determinism comes from hashing (sun_i, particle_i, epoch); no
        // persistent state needed across frames.
        if (!s.flare_texture_path.empty()) {
            assets::Texture* flare_tex = ensure_texture(s.flare_texture_path);
            if (flare_tex) {
                ensure_flare_quad();
                auto& flare_shader = pipeline.sun_flare_shader();
                flare_shader.use();
                flare_shader.set_mat4("u_proj", camera.proj_matrix());
                flare_shader.set_mat4("u_view", camera.view_matrix());
                flare_shader.set_int("u_texture", 0);
                flare_shader.set_int("u_grid_size", kFlareGridSize);

                glEnable(GL_BLEND);
                glBlendFunc(GL_SRC_ALPHA, GL_ONE);
                glDepthMask(GL_FALSE);
                glDisable(GL_CULL_FACE);
                glActiveTexture(GL_TEXTURE0);
                glBindTexture(GL_TEXTURE_2D, flare_tex->id());
                glBindVertexArray(flare_quad_vao_);

                const std::uint32_t sun_i = static_cast<std::uint32_t>(
                    &s - suns.data());

                for (int p_i = 0; p_i < kFlareParticleCount; ++p_i) {
                    auto rand01 = [&](std::uint32_t salt, std::uint32_t epoch) {
                        std::uint32_t h = sun_i   * 73856093u
                                        ^ static_cast<std::uint32_t>(p_i) * 19349663u
                                        ^ salt    * 83492791u
                                        ^ epoch   * 2246822519u;
                        h = (h ^ (h >> 13)) * 2654435761u;
                        h ^= h >> 16;
                        return float(h & 0xFFFFFFu) / float(0x1000000u);
                    };

                    // Birth phase keeps particles desynchronised; constant
                    // per (sun, particle) across all epochs.
                    const float phase01 = rand01(99u, 0u);
                    const float local_t =
                        static_cast<float>(now_seconds) / kFlareLifetimeSec
                        + phase01;
                    const std::uint32_t epoch =
                        static_cast<std::uint32_t>(std::floor(local_t));
                    const float t_within = local_t - std::floor(local_t);

                    // Each epoch reseeds position + size only; cell index
                    // is a linear function of t_within so the puff plays
                    // through frames 0..63 of the atlas in sequence over
                    // its lifetime.  Respawns at a new spot with a new
                    // size at every epoch boundary.
                    const float u01    = rand01(0u, epoch);
                    const float v01    = rand01(1u, epoch);
                    const float size01 = rand01(2u, epoch);
                    const int cell_total = kFlareGridSize * kFlareGridSize;
                    int cell = static_cast<int>(
                        t_within * static_cast<float>(cell_total));
                    if (cell < 0)            cell = 0;
                    if (cell >= cell_total)  cell = cell_total - 1;

                    // Uniform on unit sphere.
                    const float z   = 2.0f * v01 - 1.0f;
                    const float r   = std::sqrt(std::max(0.0f, 1.0f - z * z));
                    const float phi = 6.2831853f * u01;
                    const glm::vec3 dir(r * std::cos(phi), r * std::sin(phi), z);

                    // Anchor slightly outside the body so the puff reads
                    // as sitting "on" the surface, not embedded in it.
                    const float anchor_radius =
                        s.radius * scale_factor * 1.05f;
                    const glm::vec3 particle_pos =
                        virtual_pos + dir * anchor_radius;

                    const float particle_half_size =
                        s.radius * scale_factor
                        * (kFlareParticleMinScale
                           + (kFlareParticleMaxScale - kFlareParticleMinScale)
                             * size01);

                    // Every frame plays at full alpha; the atlas's own
                    // per-cell alpha (sparse at row 0 and row 7, dense
                    // in the middle rows) supplies the natural fade-in
                    // and dissipation.
                    const float alpha = 1.0f;

                    flare_shader.set_vec3("u_world_center", particle_pos);
                    flare_shader.set_float("u_half_size", particle_half_size);
                    flare_shader.set_int("u_frame", cell);
                    flare_shader.set_float("u_alpha", alpha);
                    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
                }

                // Restore the sphere pass's state for the next iteration
                // of the suns loop. The outer cleanup at the end of
                // render() handles the final restore.
                glEnable(GL_CULL_FACE);
                glCullFace(GL_FRONT);
                glDepthMask(GL_TRUE);
                glDisable(GL_BLEND);
                glBindVertexArray(sphere->vao());
                shader.use();   // rebind sun shader for next iteration's body draw
            }
        }
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}

}  // namespace renderer
