// native/src/renderer/far_pass.cc
// Far tier impostors (docs/superpowers/specs/2026-10-01-far-tier-design.md, §3).
#include "renderer/far_pass.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#include <glad/glad.h>

#include <glm/glm.hpp>

#include <scenegraph/camera.h>

#include "renderer/asset_path.h"
#include "renderer/frame.h"
#include "renderer/pipeline.h"
#include "renderer/rock_shading.h"
#include "renderer/shader.h"

namespace renderer {
namespace {

constexpr GLsizei kInstanceStride = static_cast<GLsizei>(sizeof(far::ImpostorGpu));
constexpr GLuint  kCentreAttrib = 7;   // impostor.vert a_centre_half..a_weights = 7..11
constexpr GLuint  kImpostorAttribs = static_cast<GLuint>(sizeof(far::ImpostorGpu) / 16);
constexpr GLsizei kSpeckStride = static_cast<GLsizei>(sizeof(SpeckGpu));
constexpr GLuint  kSpeckAttrib = 7;    // speck.vert a_pos_p, a_albedo_alpha = 7, 8
constexpr int     kDilatePasses = 8;

// Atlas conventions. The bake (native/src/rockgen/src/impostor.cc) writes each
// cell with screen y growing DOWN, and assets::upload_image does not flip
// rows, so atlas row 0 (t = 0) is the TOP of a view.
//  - u_uv_flip_y = 0: pinned by FarPassGLTest.AtlasOrientation (1 shows the
//    rock upside down).
//  - The atlas normal is (n.right, n.up, n.dir) of its view; opaque.frag's
//    IMPOSTOR_VIEWS path rebuilds it in render space from the view's basis
//    (no tangent frame, so no green flip). Its sense is pinned by
//    FarPassGLTest.LightingSide.
constexpr int kUvFlipY = 0;

GLuint make_1x1(const std::uint8_t rgba[4]) {
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return t;
}

assets::Texture upload_atlas(assets::Image img) {
    dilate_coverage(img, kDilatePasses);
    assets::Texture t = assets::upload_image(img, /*generate_mipmaps=*/true);
    // Cells tile the atlas: never wrap one edge's texels onto the other.
    glBindTexture(GL_TEXTURE_2D, t.id());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);
    return t;
}

assets::Image read_image(const std::string& path) {
    const std::string resolved = is_absolute_asset_path(path) ? path : project_asset_path(path);
    std::ifstream in(resolved, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open " + resolved);
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    return assets::decode_image(bytes);
}

}  // namespace

void dilate_coverage(assets::Image& img, int passes) {
    if (img.format != assets::Image::Format::RGBA8) return;
    const int w = static_cast<int>(img.width), h = static_cast<int>(img.height);
    std::vector<std::uint8_t> filled(static_cast<std::size_t>(w) * static_cast<std::size_t>(h));
    for (std::size_t i = 0; i < filled.size(); ++i) filled[i] = img.pixels[i * 4 + 3] != 0;
    for (int pass = 0; pass < passes; ++pass) {
        std::vector<std::uint8_t> next = filled;
        bool grew = false;
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                const std::size_t i = static_cast<std::size_t>(y) * w + x;
                if (filled[i]) continue;
                int sum[3] = {0, 0, 0}, n = 0;
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int nx = x + dx, ny = y + dy;
                        if ((dx == 0 && dy == 0) || nx < 0 || ny < 0 || nx >= w || ny >= h)
                            continue;
                        const std::size_t j = static_cast<std::size_t>(ny) * w + nx;
                        if (!filled[j]) continue;
                        for (int k = 0; k < 3; ++k) sum[k] += img.pixels[j * 4 + k];
                        ++n;
                    }
                if (n == 0) continue;
                for (int k = 0; k < 3; ++k)
                    img.pixels[i * 4 + k] = static_cast<std::uint8_t>((sum[k] + n / 2) / n);
                next[i] = 1;
                grew = true;
            }
        }
        filled.swap(next);
        if (!grew) break;
    }
}

FarPass::~FarPass() {
    atlases_.clear();
    if (vao_ != 0) { GLuint v = vao_; glDeleteVertexArrays(1, &v); }
    if (corner_vbo_ != 0) { GLuint b = corner_vbo_; glDeleteBuffers(1, &b); }
    if (instance_vbo_ != 0) { GLuint b = instance_vbo_; glDeleteBuffers(1, &b); }
    if (speck_vao_ != 0) { GLuint v = speck_vao_; glDeleteVertexArrays(1, &v); }
    if (speck_vbo_ != 0) { GLuint b = speck_vbo_; glDeleteBuffers(1, &b); }
    if (rock_speck_vao_ != 0) { GLuint v = rock_speck_vao_; glDeleteVertexArrays(1, &v); }
    if (rock_speck_vbo_ != 0) { GLuint b = rock_speck_vbo_; glDeleteBuffers(1, &b); }
    if (rock_puff_vao_ != 0) { GLuint v = rock_puff_vao_; glDeleteVertexArrays(1, &v); }
    if (rock_puff_vbo_ != 0) { GLuint b = rock_puff_vbo_; glDeleteBuffers(1, &b); }
    if (white_texture_ != 0) { GLuint t = white_texture_; glDeleteTextures(1, &t); }
    if (black_texture_ != 0) { GLuint t = black_texture_; glDeleteTextures(1, &t); }
}

void FarPass::set_atlas_paths(std::vector<std::pair<std::string, std::string>> albedo_normal) {
    paths_ = std::move(albedo_normal);
    failed_.clear();   // new paths: a failure is retried, not remembered
}

void FarPass::install_atlas(int index, assets::Image albedo, assets::Image normal) {
    AtlasGpu a{upload_atlas(std::move(albedo)), upload_atlas(std::move(normal))};
    atlases_.insert_or_assign(index, std::move(a));
    failed_.erase(index);
}

void FarPass::debug_set_atlas(int index, const assets::Image& albedo, const assets::Image& normal) {
    install_atlas(index, albedo, normal);
}

const FarPass::AtlasGpu* FarPass::atlas_for(int index) {
    if (auto it = atlases_.find(index); it != atlases_.end()) return &it->second;
    if (failed_.count(index) != 0) return nullptr;
    if (index < 0 || static_cast<std::size_t>(index) >= paths_.size()) {
        failed_.insert(index);
        std::fprintf(stderr, "[far_pass] no atlas path for catalogue rock %d\n", index);
        return nullptr;
    }
    const auto& [albedo_path, normal_path] = paths_[static_cast<std::size_t>(index)];
    try {
        install_atlas(index, read_image(albedo_path), read_image(normal_path));
    } catch (const std::exception& e) {
        failed_.insert(index);
        std::fprintf(stderr, "[far_pass] impostor atlas for catalogue rock %d not loaded: %s\n",
                     index, e.what());
        return nullptr;
    }
    return &atlases_.at(index);
}

void FarPass::ensure_geometry() {
    if (vao_ != 0) return;
    // Strip order (-1,-1), (-1,+1), (+1,-1), (+1,+1): the first triangle's
    // normal is up x right, which impostor.vert points at the eye, so the
    // quad is front-facing (CCW) under the pipeline's back-face cull.
    const float corners[8] = {-1.0f, -1.0f, -1.0f, 1.0f, 1.0f, -1.0f, 1.0f, 1.0f};
    GLuint vao = 0, vbo = 0, ibo = 0;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glGenBuffers(1, &ibo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(corners), corners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindBuffer(GL_ARRAY_BUFFER, ibo);
    for (GLuint k = 0; k < kImpostorAttribs; ++k) {
        glEnableVertexAttribArray(kCentreAttrib + k);
        glVertexAttribPointer(kCentreAttrib + k, 4, GL_FLOAT, GL_FALSE, kInstanceStride,
                              reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
        glVertexAttribDivisor(kCentreAttrib + k, 1);
    }
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    vao_ = vao;
    corner_vbo_ = vbo;
    instance_vbo_ = ibo;
}

void FarPass::render_impostors(const std::vector<far::ImpostorBin>& bins,
                               const scenegraph::Camera& cam, Pipeline& pipeline,
                               const Lighting& lighting, float ambient_scale,
                               float rim_strength) {
    draw_impostors(bins, cam, pipeline, lighting, ambient_scale, rim_strength, /*blended=*/false);
}

void FarPass::render_impostors_blended(const std::vector<far::ImpostorBin>& bins,
                                       const scenegraph::Camera& cam, Pipeline& pipeline,
                                       const Lighting& lighting, float ambient_scale,
                                       float rim_strength) {
    draw_impostors(bins, cam, pipeline, lighting, ambient_scale, rim_strength, /*blended=*/true);
}

void FarPass::draw_impostors(const std::vector<far::ImpostorBin>& bins,
                             const scenegraph::Camera& cam, Pipeline& pipeline,
                             const Lighting& lighting, float ambient_scale, float rim_strength,
                             bool blended) {
    // Which bins draw: non-empty, with an atlas (loaded lazily here).
    std::vector<std::pair<const far::ImpostorBin*, const AtlasGpu*>> draws;
    for (const auto& bin : bins) {
        if (bin.items.empty()) continue;
        if (const AtlasGpu* a = atlas_for(bin.rock)) draws.emplace_back(&bin, a);
    }
    if (draws.empty()) return;

    if (white_texture_ == 0) {
        const std::uint8_t white[4] = {255, 255, 255, 255};
        white_texture_ = make_1x1(white);
    }
    if (black_texture_ == 0) {
        const std::uint8_t black[4] = {0, 0, 0, 255};
        black_texture_ = make_1x1(black);
    }
    ensure_geometry();

    Shader& s = pipeline.impostor_shader();
    configure_rock_program(s, cam, lighting, ambient_scale, rim_strength, white_texture_,
                           black_texture_);
    s.set_int("u_uv_flip_y", kUvFlipY);
    s.set_vec3("u_diffuse_color", glm::vec3(1.0f));
    s.set_vec3("u_emissive_color", glm::vec3(0.0f));
    s.set_int("u_base_color", 0);
    s.set_int("u_glow_map", 1);
    s.set_int("u_specular_map", 2);
    s.set_int("u_specular_enabled", 0);
    s.set_int("u_normal_map", 4);
    s.set_int("u_normal_enabled", 0);   // IMPOSTOR_VIEWS blends the atlas normal itself
    s.set_int("u_coverage_cutout", 1);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, black_texture_);
    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_2D, black_texture_);

    // Every drawn bin's instances into one stream buffer, bin after bin.
    staging_.clear();
    std::vector<std::size_t> offset(draws.size());
    for (std::size_t d = 0; d < draws.size(); ++d) {
        offset[d] = staging_.size() * sizeof(far::ImpostorGpu);
        staging_.insert(staging_.end(), draws[d].first->items.begin(), draws[d].first->items.end());
    }
    const std::size_t bytes = staging_.size() * sizeof(far::ImpostorGpu);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    if (bytes > instance_capacity_) instance_capacity_ = bytes;   // grows only
    // Orphan, then fill: the driver need not wait on last frame's draws.
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(instance_capacity_), nullptr,
                 GL_STREAM_DRAW);
    glBufferSubData(GL_ARRAY_BUFFER, 0, static_cast<GLsizeiptr>(bytes), staging_.data());

    // Translucent: premultiplied over, depth-tested, no depth writes. The
    // blend function is QUERIED and put back as found (as render_specks).
    GLint blend_src_rgb = GL_ONE, blend_dst_rgb = GL_ZERO;
    GLint blend_src_a = GL_ONE, blend_dst_a = GL_ZERO;
    if (blended) {
        s.set_int("u_impostor_blend", 1);
        glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
        glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
        glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
        glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
    }

    // Solid impostors on a multisampled target: the silhouette goes through
    // alpha-to-coverage (smooth MSAA edge, no screen-fixed noise to shimmer).
    GLint fb_samples = 0;
    if (!blended) glGetIntegerv(GL_SAMPLES, &fb_samples);
    const bool a2c = !blended && fb_samples > 1;
    s.set_int("u_alpha_to_coverage", a2c ? 1 : 0);
    if (a2c) glEnable(GL_SAMPLE_ALPHA_TO_COVERAGE);

    glBindVertexArray(vao_);
    for (std::size_t d = 0; d < draws.size(); ++d) {
        for (GLuint k = 0; k < kImpostorAttribs; ++k) {
            glVertexAttribPointer(
                kCentreAttrib + k, 4, GL_FLOAT, GL_FALSE, kInstanceStride,
                reinterpret_cast<void*>(static_cast<std::uintptr_t>(offset[d] + k * 16)));
        }
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, draws[d].second->albedo.id());
        glActiveTexture(GL_TEXTURE4);
        glBindTexture(GL_TEXTURE_2D, draws[d].second->normal.id());
        glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4,
                              static_cast<GLsizei>(draws[d].first->items.size()));
        ++draw_calls_;
    }

    // The cutout and the blend mode are per-program state: never leave them on.
    s.set_int("u_coverage_cutout", 0);
    if (a2c) glDisable(GL_SAMPLE_ALPHA_TO_COVERAGE);
    s.set_int("u_alpha_to_coverage", 0);
    if (blended) {
        s.set_int("u_impostor_blend", 0);
        glDepthMask(GL_TRUE);
        glBlendFuncSeparate(static_cast<GLenum>(blend_src_rgb), static_cast<GLenum>(blend_dst_rgb),
                            static_cast<GLenum>(blend_src_a), static_cast<GLenum>(blend_dst_a));
        glDisable(GL_BLEND);
    }
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glActiveTexture(GL_TEXTURE0);
}

void FarPass::render_specks(const std::vector<SpeckGpu>& specks, const scenegraph::Camera& cam,
                            Pipeline& pipeline, const Lighting& lighting,
                            float ambient_scale, float speck_gain, int viewport_w,
                            int viewport_h) {
    if (specks.empty()) return;
    ensure_geometry();   // the shared corner strip
    if (speck_vao_ == 0) {
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, corner_vbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        for (GLuint k = 0; k < 2; ++k) {
            glEnableVertexAttribArray(kSpeckAttrib + k);
            glVertexAttribPointer(kSpeckAttrib + k, 4, GL_FLOAT, GL_FALSE, kSpeckStride,
                                  reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
            glVertexAttribDivisor(kSpeckAttrib + k, 1);
        }
        glBindVertexArray(0);
        speck_vao_ = vao;
        speck_vbo_ = vbo;
    }

    const std::size_t bytes = specks.size() * sizeof(SpeckGpu);
    glBindBuffer(GL_ARRAY_BUFFER, speck_vbo_);
    if (bytes > speck_capacity_) speck_capacity_ = bytes;   // grows only
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(speck_capacity_), nullptr,
                 GL_STREAM_DRAW);
    glBufferSubData(GL_ARRAY_BUFFER, 0, static_cast<GLsizeiptr>(bytes), specks.data());

    // The lighting inputs configure_rock_program gives a mesh rock.
    Shader& s = pipeline.speck_shader();
    s.use();
    s.set_mat4("u_view", cam.view_matrix());
    s.set_mat4("u_proj", cam.proj_matrix());
    s.set_vec3("u_camera_pos_ws", glm::vec3(glm::inverse(cam.view_matrix())[3]));
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }
    s.set_float("u_speck_gain", speck_gain);
    s.set_vec2("u_viewport", glm::vec2(static_cast<float>(viewport_w),
                                       static_cast<float>(viewport_h)));
    GLint vp[4] = {0, 0, 0, 0};            // the square kernel works in window coords
    glGetIntegerv(GL_VIEWPORT, vp);
    s.set_vec2("u_viewport_origin", glm::vec2(static_cast<float>(vp[0]), static_cast<float>(vp[1])));

    // The blend function is QUERIED and put back as found, not reset to a
    // guessed frame default: passes disagree on what that default is.
    GLint blend_src_rgb = GL_ONE, blend_dst_rgb = GL_ZERO;
    GLint blend_src_a = GL_ONE, blend_dst_a = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);

    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);   // premultiplied
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(speck_vao_);
    glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, static_cast<GLsizei>(specks.size()));
    ++draw_calls_;

    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    // Restore the frame defaults: cull on, depth writes on, blend off; and
    // the blend function as it was found.
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glBlendFuncSeparate(static_cast<GLenum>(blend_src_rgb), static_cast<GLenum>(blend_dst_rgb),
                        static_cast<GLenum>(blend_src_a), static_cast<GLenum>(blend_dst_a));
    glDisable(GL_BLEND);
}

void FarPass::upload_rock_specks(const std::vector<rockfield::RockSpeckGpu>& specks) {
    ensure_geometry();   // the shared corner strip
    if (rock_speck_vao_ == 0) {
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, corner_vbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        for (GLuint k = 0; k < 3; ++k) {   // a_pos_r, a_albedo_u, a_seed = 7, 8, 9
            glEnableVertexAttribArray(kSpeckAttrib + k);
            glVertexAttribPointer(kSpeckAttrib + k, 4, GL_FLOAT, GL_FALSE,
                                  static_cast<GLsizei>(sizeof(rockfield::RockSpeckGpu)),
                                  reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
            glVertexAttribDivisor(kSpeckAttrib + k, 1);
        }
        glBindVertexArray(0);
        rock_speck_vao_ = vao;
        rock_speck_vbo_ = vbo;
    }
    glBindBuffer(GL_ARRAY_BUFFER, rock_speck_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(specks.size() * sizeof(rockfield::RockSpeckGpu)),
                 specks.empty() ? nullptr : specks.data(), GL_STATIC_DRAW);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    rock_speck_count_ = static_cast<int>(specks.size());
}

void FarPass::render_rock_specks(const RockSpeckDraw& d, const scenegraph::Camera& cam,
                                 Pipeline& pipeline, const Lighting& lighting,
                                 float ambient_scale, float speck_gain, int viewport_w,
                                 int viewport_h) {
    if (rock_speck_count_ <= 0 || rock_speck_vao_ == 0) return;
    Shader& s = pipeline.rock_speck_shader();
    s.use();
    s.set_mat4("u_view", cam.view_matrix());
    s.set_mat4("u_proj", cam.proj_matrix());
    const glm::vec3 eye = glm::vec3(glm::inverse(cam.view_matrix())[3]);
    s.set_vec3("u_camera_pos_ws", eye);
    s.set_vec3("u_eye", eye);
    s.set_vec3("u_offset", d.offset);
    s.set_float("u_in_gu", d.in_gu);
    s.set_float("u_in_fade_gu", d.in_fade_gu);
    s.set_float("u_out_gu", d.out_gu);
    s.set_float("u_out_fade_gu", d.out_fade_gu);
    s.set_float("u_keep_d0_gu", d.keep_d0_gu);
    s.set_float("u_keep_band", d.keep_band);
    s.set_float("u_keep_power", d.keep_power);
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }
    s.set_float("u_speck_gain", speck_gain * d.gain);
    s.set_vec2("u_viewport", glm::vec2(static_cast<float>(viewport_w),
                                       static_cast<float>(viewport_h)));
    GLint vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp);
    s.set_vec2("u_viewport_origin", glm::vec2(static_cast<float>(vp[0]), static_cast<float>(vp[1])));

    GLint blend_src_rgb = GL_ONE, blend_dst_rgb = GL_ZERO;
    GLint blend_src_a = GL_ONE, blend_dst_a = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);   // premultiplied
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(rock_speck_vao_);
    glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, static_cast<GLsizei>(rock_speck_count_));
    ++draw_calls_;

    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glBlendFuncSeparate(static_cast<GLenum>(blend_src_rgb), static_cast<GLenum>(blend_dst_rgb),
                        static_cast<GLenum>(blend_src_a), static_cast<GLenum>(blend_dst_a));
    glDisable(GL_BLEND);
}

void FarPass::upload_rock_puffs(const std::vector<rockfield::PuffGpu>& puffs) {
    ensure_geometry();   // the shared corner strip
    if (rock_puff_vao_ == 0) {
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, corner_vbo_);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        for (GLuint k = 0; k < 2; ++k) {
            glEnableVertexAttribArray(kSpeckAttrib + k);
            glVertexAttribPointer(kSpeckAttrib + k, 4, GL_FLOAT, GL_FALSE,
                                  static_cast<GLsizei>(sizeof(rockfield::PuffGpu)),
                                  reinterpret_cast<void*>(static_cast<std::uintptr_t>(k * 16)));
            glVertexAttribDivisor(kSpeckAttrib + k, 1);
        }
        glBindVertexArray(0);
        rock_puff_vao_ = vao;
        rock_puff_vbo_ = vbo;
    }
    glBindBuffer(GL_ARRAY_BUFFER, rock_puff_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(puffs.size() * sizeof(rockfield::PuffGpu)),
                 puffs.empty() ? nullptr : puffs.data(), GL_STATIC_DRAW);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    rock_puff_count_ = static_cast<int>(puffs.size());
}

void FarPass::render_rock_puffs(const glm::vec3& offset, const rockfield::PuffDials& d,
                                const scenegraph::Camera& cam, Pipeline& pipeline,
                                const Lighting& lighting, float ambient_scale) {
    if (rock_puff_count_ <= 0 || rock_puff_vao_ == 0) return;
    Shader& s = pipeline.rock_puff_shader();
    s.use();
    s.set_mat4("u_view", cam.view_matrix());
    s.set_mat4("u_proj", cam.proj_matrix());
    const glm::vec3 eye = glm::vec3(glm::inverse(cam.view_matrix())[3]);
    s.set_vec3("u_camera_pos_ws", eye);
    s.set_vec3("u_eye", eye);
    s.set_vec3("u_offset", offset);
    s.set_float("u_opacity", d.opacity);
    s.set_float("u_start_gu", d.start_gu);
    s.set_float("u_ramp_gu", d.ramp_gu);
    s.set_float("u_near_fade", d.near_fade);
    s.set_float("u_brightness", d.brightness);
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }
    GLint blend_src_rgb = GL_ONE, blend_dst_rgb = GL_ZERO;
    GLint blend_src_a = GL_ONE, blend_dst_a = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);   // premultiplied
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(rock_puff_vao_);
    glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, static_cast<GLsizei>(rock_puff_count_));
    ++draw_calls_;
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glBlendFuncSeparate(static_cast<GLenum>(blend_src_rgb), static_cast<GLenum>(blend_dst_rgb),
                        static_cast<GLenum>(blend_src_a), static_cast<GLenum>(blend_dst_a));
    glDisable(GL_BLEND);
}

}  // namespace renderer
