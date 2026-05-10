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
                     Pipeline& pipeline) {
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

    for (const auto& s : suns) {
        assets::Texture* tex = ensure_texture(s.base_texture_path);
        if (!tex) continue;

        // Body: opaque sphere scaled to radius, translated to world position
        glm::mat4 model = glm::translate(glm::mat4(1.0f), s.position)
                        * glm::scale(glm::mat4(1.0f), glm::vec3(s.radius));
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
        if (s.corona_radius > s.radius) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            glDepthMask(GL_FALSE);
            glm::mat4 corona_model =
                glm::translate(glm::mat4(1.0f), s.position)
                * glm::scale(glm::mat4(1.0f), glm::vec3(s.corona_radius));
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
