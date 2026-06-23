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

NebulaPass::~NebulaPass() {
    // Free the billboard quad VBO/VAO if they were created.
    if (quad_vao_ != 0) {
        glDeleteVertexArrays(1, &quad_vao_);
        quad_vao_ = 0;
    }
    if (quad_vbo_ != 0) {
        glDeleteBuffers(1, &quad_vbo_);
        quad_vbo_ = 0;
    }
}

void NebulaPass::initialize_gl() {
    if (initialized_) return;

    // Unit sphere shared by the inside-fog (Task 6) draw.
    // Same build_uv_sphere the sun/backdrop passes use; 256 tris is
    // plenty since the fragment shader does the analytic ray-sphere integral
    // (the mesh only has to rasterise the silhouette).
    assets::MeshCpu cpu = build_uv_sphere(256);
    sphere_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));

    // Camera-facing billboard quad for the outside shell (Task 7).
    // Four corners in [-1,1]^2 as a triangle strip.
    // Attribute: location 0, vec2.
    const float quad_corners[4][2] = {
        { -1.0f, -1.0f },
        {  1.0f, -1.0f },
        { -1.0f,  1.0f },
        {  1.0f,  1.0f },
    };
    glGenVertexArrays(1, &quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindVertexArray(quad_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad_corners), quad_corners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);

    initialized_ = true;
}

// Helper: load a TGA from `path` into *out_tex_. Returns the GL id (0 on failure/empty).
static unsigned int load_texture_from_path(const std::string& path,
                                           std::unique_ptr<assets::Texture>& out_tex) {
    if (path.empty()) {
        out_tex = std::make_unique<assets::Texture>();  // sentinel (id == 0)
        return 0;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[nebula] failed to open '%s'\n", path.c_str());
        out_tex = std::make_unique<assets::Texture>();
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
        out_tex = std::make_unique<assets::Texture>(
            assets::upload_image(img, /*generate_mipmaps=*/true));
        return out_tex->id();
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[nebula] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        out_tex = std::make_unique<assets::Texture>();
        return 0;
    }
}

unsigned int NebulaPass::ensure_overlay(const std::string& path) {
    if (overlay_tex_ && overlay_path_ == path) {
        return overlay_tex_->id();
    }
    overlay_path_ = path;
    return load_texture_from_path(path, overlay_tex_);
}

unsigned int NebulaPass::ensure_external(const std::string& path) {
    if (external_tex_ && external_path_ == path) {
        return external_tex_->id();
    }
    external_path_ = path;
    return load_texture_from_path(path, external_tex_);
}

void NebulaPass::render(const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const std::vector<NebulaVolume>& volumes) {
    // Stock-BC byte-identity: empty list => zero GL work.
    if (!enabled_ || volumes.empty()) return;
    if (!initialized_) initialize_gl();
    if (!sphere_ || sphere_->vao() == 0) return;

    const glm::vec3 eye = camera.eye;

    // ─── INSIDE-FOG PASS ──────────────────────────────────────────────────────
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
    shader.set_vec3("u_eye",  eye);

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

    // ─── OUTSIDE BILLBOARD SHELL PASS ────────────────────────────────────────
    // For each sphere where the camera is OUTSIDE the volume, draw a
    // camera-facing additive billboard (nebulaexternal.tga) sized to the
    // sphere. Cross-fades out as the camera approaches the rim.
    if (quad_vao_ != 0) {
        // External texture: loaded from the first volume that names one.
        unsigned int external_id = 0;
        for (const auto& v : volumes) {
            if (!v.external_tex.empty()) {
                external_id = ensure_external(v.external_tex);
                break;
            }
        }

        auto& shell = pipeline.nebula_shell_shader();
        shell.use();
        shell.set_mat4("u_view", camera.view_matrix());
        shell.set_mat4("u_proj", camera.proj_matrix());

        // Additive blend: GL_ONE, GL_ONE.
        glBlendFunc(GL_ONE, GL_ONE);
        // depth test stays enabled (GL_LEQUAL), depth-write off — already set.
        glCullFace(GL_BACK);   // billboard is a screen-facing quad; cull back

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, external_id);
        shell.set_int("u_external", 0);

        glBindVertexArray(quad_vao_);

        for (const auto& v : volumes) {
            shell.set_vec3("u_rgb", v.rgb);
            shell.set_float("u_brightness", 1.0f);

            for (const auto& s : v.spheres) {
                const glm::vec3 centre(s.x, s.y, s.z);
                const float     radius = s.w;
                const float     dist   = glm::length(eye - centre);

                // Only draw the shell when the camera is OUTSIDE the sphere.
                if (dist <= radius) continue;

                // Rim cross-fade: 0 at rim, 1 at 1.5*radius (rimBand = 0.5*radius).
                const float rim_fade = glm::clamp(
                    (dist - radius) / (radius * 0.5f), 0.0f, 1.0f);

                shell.set_vec3("u_center",   centre);
                shell.set_float("u_size",    radius);
                shell.set_float("u_rim_fade", rim_fade);

                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            }
        }

        glBindVertexArray(0);
    }

    // ─── RESTORE CANONICAL GL STATE ──────────────────────────────────────────
    // Leave the pipeline in the state the next pass expects: back-face cull,
    // depth test on with LESS, depth writes on, blend disabled.
    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // reset blend func to default
    glDisable(GL_BLEND);
}

}  // namespace renderer
