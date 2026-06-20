// native/src/renderer/backdrop_pass.cc
#include "renderer/backdrop_pass.h"

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
                          Pipeline& pipeline,
                          bool procedural,
                          float now_seconds) {
    if (backdrops.empty()) return;
    const glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    draw_backdrops(backdrops, view_no_t, camera.proj_matrix(),
                   pipeline, procedural, now_seconds);
}

void BackdropPass::draw_backdrops(const std::vector<Backdrop>& backdrops,
                                  const glm::mat4& view_no_translation,
                                  const glm::mat4& proj,
                                  Pipeline& pipeline,
                                  bool procedural,
                                  float now_seconds) {
    auto& shader = pipeline.backdrop_shader();
    shader.use();
    shader.set_mat4("u_view_no_translation", view_no_translation);
    shader.set_mat4("u_proj", proj);

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);  // we render the inside of the sphere

    for (const auto& b : backdrops) {
        assets::Mesh* sphere = ensure_sphere(b.target_poly_count);
        assets::Texture* tex = ensure_texture(b.texture_path);
        if (!sphere) continue;
        if (!tex && !procedural) continue;

        if (b.kind == BackdropKind::Backdrop) {
            glEnable(GL_BLEND);
            // Additive: sky features (nebulae, galaxies) emit light over the
            // starfield — they brighten, never darken. Alpha (ONE_MINUS_SRC_ALPHA)
            // blended a distance-dimmed colour *over* the stars, subtracting
            // brightness and painting hard dark wedges where patches overlapped.
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            shader.set_int("u_use_alpha", 1);
        } else {
            glDisable(GL_BLEND);
            shader.set_int("u_use_alpha", 0);
        }

        shader.set_mat3("u_world_rotation", b.world_rotation);
        shader.set_vec2("u_tile", glm::vec2(b.h_tile, b.v_tile));
        shader.set_vec2("u_span", glm::vec2(b.h_span, b.v_span));

        shader.set_int("u_procedural", procedural ? 1 : 0);
        shader.set_int("u_proc_kind", b.proc_kind);
        shader.set_vec3("u_color", b.color);
        shader.set_float("u_coverage", b.coverage);
        shader.set_float("u_seed", b.seed);
        shader.set_float("u_time", now_seconds);

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex ? tex->id() : 0);
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

bool BackdropPass::bake(const std::vector<Backdrop>& backdrops,
                        Pipeline& pipeline, float now_seconds) {
    if (backdrops.empty()) return false;
    if (!cubemap_.allocate(kSkyFaceSize)) return false;

    GLint prev_fbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    GLint prev_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, prev_vp);

    glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS);
    const glm::mat4 proj = glm::perspective(glm::radians(90.0f), 1.0f, 0.1f, 10.0f);

    // Canonical GL cubemap face orientations (camera at origin). The up vectors
    // follow the cube's left-handed face convention so a later
    // texture(cube, worldDir) sample returns the colour baked for worldDir.
    struct Face { glm::vec3 dir; glm::vec3 up; };
    static const Face kFaces[6] = {
        {{ 1,  0,  0}, {0, -1,  0}},  // +X
        {{-1,  0,  0}, {0, -1,  0}},  // -X
        {{ 0,  1,  0}, {0,  0,  1}},  // +Y
        {{ 0, -1,  0}, {0,  0, -1}},  // -Y
        {{ 0,  0,  1}, {0, -1,  0}},  // +Z
        {{ 0,  0, -1}, {0, -1,  0}},  // -Z
    };

    for (int i = 0; i < 6; ++i) {
        cubemap_.bind_face(i);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        const glm::mat4 view =
            glm::lookAt(glm::vec3(0.0f), kFaces[i].dir, kFaces[i].up);
        const glm::mat4 view_no_t = glm::mat4(glm::mat3(view));
        draw_backdrops(backdrops, view_no_t, proj, pipeline,
                       /*procedural=*/true, now_seconds);
    }
    cubemap_.generate_mips();

    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));
    glViewport(prev_vp[0], prev_vp[1], prev_vp[2], prev_vp[3]);
    ++bakes_count_;
    return true;
}

void BackdropPass::render_cubemap(const scenegraph::Camera& camera,
                                  Pipeline& pipeline) {
    if (!cubemap_.valid()) return;
    auto& shader = pipeline.skybox_shader();
    shader.use();
    const glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    shader.set_mat4("u_view_no_translation", view_no_t);
    shader.set_mat4("u_proj", camera.proj_matrix());

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);  // inside of the proxy sphere
    glDisable(GL_BLEND);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_CUBE_MAP, cubemap_.texture());
    shader.set_int("u_skybox", 0);

    assets::Mesh* sphere = ensure_sphere(256);  // sample proxy; detail is in the cube
    if (sphere) {
        glBindVertexArray(sphere->vao());
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}

bool backdrops_are_procedural(const std::vector<Backdrop>& backdrops) {
    if (backdrops.empty()) return false;
    for (const auto& b : backdrops) {
        if (!b.texture_path.empty()) return false;
    }
    return true;
}

bool backdrops_equal(const std::vector<Backdrop>& a,
                     const std::vector<Backdrop>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        const Backdrop& x = a[i];
        const Backdrop& y = b[i];
        if (x.texture_path != y.texture_path) return false;
        if (x.kind != y.kind) return false;
        if (x.h_tile != y.h_tile || x.v_tile != y.v_tile) return false;
        if (x.h_span != y.h_span || x.v_span != y.v_span) return false;
        if (x.world_rotation != y.world_rotation) return false;
        if (x.target_poly_count != y.target_poly_count) return false;
        if (x.proc_kind != y.proc_kind) return false;
        if (x.color != y.color) return false;
        if (x.coverage != y.coverage) return false;
        if (x.seed != y.seed) return false;
    }
    return true;
}

}  // namespace renderer
