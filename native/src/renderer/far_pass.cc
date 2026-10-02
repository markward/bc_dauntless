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
constexpr GLuint  kCentreAttrib = 7;   // impostor.vert a_centre_half..a_up_dither = 7..9
constexpr GLsizei kSpeckStride = static_cast<GLsizei>(sizeof(SpeckGpu));
constexpr GLuint  kSpeckAttrib = 7;    // speck.vert a_pos_p, a_albedo_alpha = 7, 8
constexpr int     kDilatePasses = 8;

// Atlas conventions. The bake (native/src/rockgen/src/impostor.cc) writes each
// 128-px cell with screen y growing DOWN, and assets::upload_image does not
// flip rows, so atlas row 0 (t = 0) is the TOP of a view.
//  - u_uv_flip_y = 0: pinned by FarPassGLTest.AtlasOrientation (1 shows the
//    rock upside down).
//  - u_normal_flip_g = 1: pinned by FarPassGLTest.LightingSide. opaque.frag's
//    derivative tangent frame takes B along +v, which on the quad is -up, while
//    the atlas green stores n.up -- so green is flipped (0 lights the rock from
//    the wrong side).
constexpr int kUvFlipY = 0;
constexpr int kNormalFlipG = 1;

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
    if (white_texture_ != 0) { GLuint t = white_texture_; glDeleteTextures(1, &t); }
    if (black_texture_ != 0) { GLuint t = black_texture_; glDeleteTextures(1, &t); }
    if (haze_vao_ != 0) { GLuint v = haze_vao_; glDeleteVertexArrays(1, &v); }
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
    // normal is up x right, which points toward the eye along the baked view,
    // so the quad is front-facing (CCW) under the pipeline's back-face cull.
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
    for (GLuint k = 0; k < 3; ++k) {
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
    s.set_int("u_normal_enabled", 1);
    s.set_float("u_normal_strength", 1.0f);
    s.set_int("u_normal_flip_g", kNormalFlipG);
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

    glBindVertexArray(vao_);
    for (std::size_t d = 0; d < draws.size(); ++d) {
        for (GLuint k = 0; k < 3; ++k) {
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

    // The cutout is per-program state: never leave it on.
    s.set_int("u_coverage_cutout", 0);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glActiveTexture(GL_TEXTURE0);
}

void FarPass::render_haze(const std::vector<far::DiscSource>& active, const glm::dvec3& origin_sys,
                          const scenegraph::Camera& cam, Pipeline& pipeline,
                          const Lighting& lighting, float ambient_scale, unsigned depth_texture,
                          const glm::mat4& inv_view_proj, float k, const far::FarDials& dials) {
    constexpr std::size_t kMaxSources = 4, kMaxRows = 32, kMaxPops = 2;
    constexpr int kMaxSteps = 64;   // far_haze.frag's loop bound
    // A source with no populations accumulates nothing: never march it.
    if (std::none_of(active.begin(), active.end(),
                     [](const far::DiscSource& src) { return !src.pops.empty(); }))
        return;
    if (active.size() > kMaxSources && !warned_haze_cap_) {
        std::fprintf(stderr, "[far] haze: %zu sources, drawing the first %zu\n", active.size(),
                     kMaxSources);
        warned_haze_cap_ = true;
    }
    if (haze_vao_ == 0) {
        GLuint v = 0;
        glGenVertexArrays(1, &v);
        haze_vao_ = v;
    }

    const glm::vec3 eye_render = glm::vec3(glm::inverse(cam.view_matrix())[3]);
    Shader& s = pipeline.far_haze_shader();
    s.use();
    s.set_mat4("u_inv_vp", inv_view_proj);
    s.set_vec3("u_eye", eye_render);
    s.set_float("u_k", k);
    s.set_float("u_p_min", dials.tiers.p_min);
    s.set_int("u_steps", std::clamp(dials.haze_steps, 1, kMaxSteps));
    s.set_float("u_gain", dials.haze_gain);
    s.set_float("u_slab_sigmas", dials.slab_sigmas);
    // The light configure_rock_program / render_specks give a rock.
    set_ambient_uniforms(s, lighting, ambient_scale);
    s.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        s.set_vec3_array("u_dir_light_dir_ws", lighting.directional_dir_ws,
                         lighting.directional_count);
        s.set_vec3_array("u_dir_light_color", lighting.directional_color,
                         lighting.directional_count);
    }
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, depth_texture);
    s.set_int("u_depth", 0);

    GLint blend_src_rgb = GL_ONE, blend_dst_rgb = GL_ZERO;
    GLint blend_src_a = GL_ONE, blend_dst_a = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB, &blend_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB, &blend_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &blend_src_a);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &blend_dst_a);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);   // premultiplied
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(haze_vao_);

    for (std::size_t si = 0; si < active.size() && si < kMaxSources; ++si) {
        const far::DiscSource& src = active[si];
        if (src.pops.empty()) continue;
        if (src.table.size() > kMaxRows && !warned_haze_table_) {
            std::fprintf(stderr, "[far] haze: source %u has %zu table rows, using the first %zu\n",
                         src.id, src.table.size(), kMaxRows);
            warned_haze_table_ = true;
        }
        if (src.pops.size() > kMaxPops && !warned_haze_pops_) {
            std::fprintf(stderr, "[far] haze: source %u has %zu populations, marching the first %zu\n",
                         src.id, src.pops.size(), kMaxPops);
            warned_haze_pops_ = true;
        }
        const int rows = static_cast<int>(std::min(src.table.size(), kMaxRows));
        float tr[kMaxRows] = {}, ta[kMaxRows] = {};
        for (int i = 0; i < rows; ++i) { tr[i] = src.table[i].x; ta[i] = src.table[i].y; }
        const int pops = static_cast<int>(std::min(src.pops.size(), kMaxPops));
        float dens[kMaxPops] = {}, alo[kMaxPops] = {}, ahi[kMaxPops] = {};
        float rmin[kMaxPops] = {}, rmax[kMaxPops] = {}, q[kMaxPops] = {};
        glm::vec3 alb[kMaxPops] = {};
        for (int i = 0; i < pops; ++i) {
            const far::Population& P = src.pops[static_cast<std::size_t>(i)];
            dens[i] = P.density_at_1; alo[i] = P.a_lo; ahi[i] = P.a_hi;
            rmin[i] = P.size.r_min; rmax[i] = P.size.r_max; q[i] = P.size.q;
            alb[i] = P.albedo;
        }
        // System -> render, in double before the cast.
        s.set_vec3("u_centre", glm::vec3(src.centre - origin_sys + glm::dvec3(eye_render)));
        s.set_vec3("u_normal", src.normal);
        s.set_float_array("u_table_r", tr, static_cast<int>(kMaxRows));
        s.set_float_array("u_table_a", ta, static_cast<int>(kMaxRows));
        s.set_int("u_table_n", rows);
        s.set_float("u_outer_fade", src.outer_fade_gu);
        s.set_float("u_h_frac", src.scale_height_frac);
        s.set_float("u_h_min", src.scale_height_min_gu);
        s.set_int("u_pop_n", pops);
        s.set_float_array("u_pop_density", dens, static_cast<int>(kMaxPops));
        s.set_float_array("u_pop_a_lo", alo, static_cast<int>(kMaxPops));
        s.set_float_array("u_pop_a_hi", ahi, static_cast<int>(kMaxPops));
        s.set_float_array("u_pop_rmin", rmin, static_cast<int>(kMaxPops));
        s.set_float_array("u_pop_rmax", rmax, static_cast<int>(kMaxPops));
        s.set_float_array("u_pop_q", q, static_cast<int>(kMaxPops));
        s.set_vec3_array("u_pop_albedo", alb, static_cast<int>(kMaxPops));
        glDrawArrays(GL_TRIANGLES, 0, 3);
        ++draw_calls_;
    }

    glBindVertexArray(0);
    glBindTexture(GL_TEXTURE_2D, 0);
    // Restore the frame defaults: depth test and writes on, cull on, blend
    // off; and the blend function as it was found.
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
    glBlendFuncSeparate(static_cast<GLenum>(blend_src_rgb), static_cast<GLenum>(blend_dst_rgb),
                        static_cast<GLenum>(blend_src_a), static_cast<GLenum>(blend_dst_a));
    glDisable(GL_BLEND);
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

}  // namespace renderer
