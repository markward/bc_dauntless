// native/src/renderer/backdrop_pass.cc
#include "renderer/backdrop_pass.h"

#include "renderer/pipeline.h"
#include "sphere_mesh.h"

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdio>
#include <fstream>

namespace renderer {

BackdropPass::~BackdropPass() {
    // assets::Mesh / assets::Texture destructors release GL handles.
    // Caller must ensure the GL context is still alive when this dtor
    // runs; host_bindings.cc resets the unique_ptr in shutdown() before
    // destroying the window for exactly that reason.
}

assets::Mesh* BackdropPass::ensure_sphere(int target_poly_count) {
    if (target_poly_count < 64) target_poly_count = 64;
    auto it = sphere_cache_.find(target_poly_count);
    if (it != sphere_cache_.end()) return it->second.get();
    assets::MeshCpu cpu = build_uv_sphere(target_poly_count);
    assets::Mesh m = assets::upload_mesh(cpu);
    auto owned = std::make_unique<assets::Mesh>(std::move(m));
    auto* raw = owned.get();
    sphere_cache_.emplace(target_poly_count, std::move(owned));
    return raw;
}

assets::Texture* BackdropPass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        // id() == 0 means a sentinel from a previous failed load.
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[backdrop] failed to open '%s'\n", path.c_str());
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
        std::fprintf(stderr, "[backdrop] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

void BackdropPass::render(const std::vector<Backdrop>& backdrops,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (backdrops.empty()) return;

    auto& shader = pipeline.backdrop_shader();
    shader.use();

    // Strip translation from the view matrix: camera-anchored position,
    // world-locked orientation. Standard skybox idiom.
    glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    shader.set_mat4("u_view_no_translation", view_no_t);
    shader.set_mat4("u_proj", camera.proj_matrix());

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glCullFace(GL_FRONT);  // we render the inside of the sphere

    for (const auto& b : backdrops) {
        assets::Mesh* sphere = ensure_sphere(b.target_poly_count);
        assets::Texture* tex = ensure_texture(b.texture_path);
        if (!sphere || !tex) continue;

        if (b.kind == BackdropKind::Backdrop) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
            shader.set_int("u_use_alpha", 1);
        } else {
            glDisable(GL_BLEND);
            shader.set_int("u_use_alpha", 0);
        }

        shader.set_mat3("u_world_rotation", b.world_rotation);
        shader.set_vec2("u_tile", glm::vec2(b.h_tile, b.v_tile));
        shader.set_vec2("u_span", glm::vec2(b.h_span, b.v_span));

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_int("u_texture", 0);

        glBindVertexArray(sphere->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glDisable(GL_BLEND);
    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}

}  // namespace renderer
