// native/src/renderer/nebula_pass.cc
#include "renderer/nebula_pass.h"

#include "renderer/pipeline.h"
#include "sphere_mesh.h"

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <vector>

namespace renderer {

NebulaPass::NebulaPass() = default;
NebulaPass::~NebulaPass() = default;

void NebulaPass::initialize_gl() {
    if (initialized_) return;
    // Unit sphere shared by the inside-fog (Task 6) and outside-shell (Task 7)
    // draws. Same build_uv_sphere the sun/backdrop passes use; 256 tris is
    // plenty since the fragment shader does the analytic ray-sphere integral
    // (the mesh only has to rasterise the silhouette).
    assets::MeshCpu cpu = build_uv_sphere(256);
    sphere_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
    initialized_ = true;
}

unsigned int NebulaPass::ensure_overlay(const std::string& path) {
    if (overlay_tex_ && overlay_path_ == path) {
        return overlay_tex_->id();
    }
    overlay_path_ = path;
    if (path.empty()) {
        overlay_tex_ = std::make_unique<assets::Texture>();  // sentinel (id == 0)
        return 0;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[nebula] failed to open '%s'\n", path.c_str());
        overlay_tex_ = std::make_unique<assets::Texture>();
        return 0;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        overlay_tex_ = std::make_unique<assets::Texture>(
            assets::upload_image(img, /*generate_mipmaps=*/true));
        return overlay_tex_->id();
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[nebula] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        overlay_tex_ = std::make_unique<assets::Texture>();
        return 0;
    }
}

void NebulaPass::render(const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const std::vector<NebulaVolume>& volumes) {
    // Stock-BC byte-identity: empty list => zero GL work.
    if (!enabled_ || volumes.empty()) return;
    if (!initialized_) initialize_gl();
    if (!sphere_ || sphere_->vao() == 0) return;

    // Inside-fog overlay texture (alpha noise). Loaded from the first volume
    // that names one; absence is tolerated (id 0 -> n=0 in the shader, whose
    // noise mix is guarded so fog stays finite).
    unsigned int overlay_id = 0;
    for (const auto& v : volumes) {
        if (!v.internal_tex.empty()) {
            overlay_id = ensure_overlay(v.internal_tex);
            break;
        }
    }

    auto& shader = pipeline.nebula_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_vec3("u_eye",  camera.eye);

    // Tunable dials (defaults; live-tuning item per the brief).
    shader.set_float("u_max_fog",      0.92f);
    shader.set_float("u_noise_amount", 0.35f);
    shader.set_float("u_noise_scale",  0.004f);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, overlay_id);
    shader.set_int("u_overlay", 0);

    // Volumetric fog: depth-TESTED back-face sphere geometry. Foreground hulls
    // closer than the back surface occlude the fog via the depth test.
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);   // draw back faces (rasterise inside OR outside)

    glBindVertexArray(sphere_->vao());
    const GLsizei index_count = static_cast<GLsizei>(sphere_->index_count());

    for (const auto& v : volumes) {
        shader.set_vec3("u_rgb",         v.rgb);
        shader.set_float("u_visibility", v.visibility);
        for (const auto& s : v.spheres) {
            shader.set_vec3("u_center",  glm::vec3(s.x, s.y, s.z));
            shader.set_float("u_radius", s.w);
            glDrawElements(GL_TRIANGLES, index_count, GL_UNSIGNED_INT, nullptr);
        }
    }

    glBindVertexArray(0);

    // Restore default GL state so later passes don't inherit ours.
    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
}

}  // namespace renderer
