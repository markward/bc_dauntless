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

#include <cstdio>
#include <fstream>

namespace renderer {

SunPass::~SunPass() {
    // assets::Mesh / assets::Texture destructors release GL handles.
    // Caller must ensure the GL context is still alive when this dtor runs.
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

void SunPass::render(const std::vector<SunDescriptor>& suns,
                     const scenegraph::Camera& camera,
                     Pipeline& pipeline,
                     double now_seconds) {
    (void)now_seconds;  // consumed by the flare-overlay draw in Task 12
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
    // overlay billboard (drawn below) provides the wider visible bulk
    // that BC's SunEffect node renders.
    [[maybe_unused]] constexpr float kFlareOverlayRatio = 1.5f;  // half-size relative to body radius

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
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}

}  // namespace renderer
