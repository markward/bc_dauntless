// native/src/renderer/planet_clipmap_atlas.cc
#include "renderer/planet_clipmap_atlas.h"

#include "renderer/shader.h"

#include "embedded_nebula_volumetric_vs.h"
#include "embedded_planet_bake_fs.h"

#include <memory>
#include <utility>

namespace renderer::planet_detail {

ClipmapAtlas::ClipmapAtlas(int levels) : levels_(levels) {
    // Compile first: a throw here must not leak the GL objects below.
    shader_ = std::make_unique<Shader>(shader_src::nebula_volumetric_vs, shader_src::planet_bake_fs);

    GLint prev_tex = 0, prev_fbo = 0;
    GLfloat prev_clear[4] = {};
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev_tex);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &prev_fbo);
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prev_clear);
    const GLboolean prev_scissor = glIsEnabled(GL_SCISSOR_TEST);

    glGenTextures(1, &tex_);
    glBindTexture(GL_TEXTURE_2D, tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, kLevelSize, kBandRows * levels_, 0,
                 GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, GLuint(prev_tex));

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex_, 0);
    // Unbaked texels must be finite zeros, never driver garbage (NaN feeds bloom).
    glDisable(GL_SCISSOR_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glClearColor(prev_clear[0], prev_clear[1], prev_clear[2], prev_clear[3]);
    if (prev_scissor) glEnable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, GLuint(prev_fbo));

    // The full-screen triangle VS reads only gl_VertexID; core profile still
    // needs a VAO bound to draw.
    glGenVertexArrays(1, &vao_);
}

ClipmapAtlas::~ClipmapAtlas() { release(); }

ClipmapAtlas::ClipmapAtlas(ClipmapAtlas&& o) noexcept
    : levels_(std::exchange(o.levels_, 0)), tex_(std::exchange(o.tex_, 0)),
      fbo_(std::exchange(o.fbo_, 0)), vao_(std::exchange(o.vao_, 0)),
      shader_(std::move(o.shader_)) {}

ClipmapAtlas& ClipmapAtlas::operator=(ClipmapAtlas&& o) noexcept {
    if (this != &o) {
        release();
        levels_ = std::exchange(o.levels_, 0);
        tex_ = std::exchange(o.tex_, 0);
        fbo_ = std::exchange(o.fbo_, 0);
        vao_ = std::exchange(o.vao_, 0);
        shader_ = std::move(o.shader_);
    }
    return *this;
}

void ClipmapAtlas::release() noexcept {
    if (tex_) glDeleteTextures(1, &tex_);
    if (fbo_) glDeleteFramebuffers(1, &fbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
    tex_ = fbo_ = vao_ = 0;
    shader_.reset();
}

namespace {

// Restores every piece of GL state bake() touches, on scope exit.
struct SavedState {
    GLint fbo = 0, program = 0, vao = 0;
    GLint viewport[4] = {}, scissor_box[4] = {};
    GLboolean scissor = GL_FALSE, blend = GL_FALSE, depth = GL_FALSE, cull = GL_FALSE;

    SavedState() {
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fbo);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_SCISSOR_BOX, scissor_box);
        scissor = glIsEnabled(GL_SCISSOR_TEST);
        blend = glIsEnabled(GL_BLEND);
        depth = glIsEnabled(GL_DEPTH_TEST);
        cull = glIsEnabled(GL_CULL_FACE);
    }
    ~SavedState() {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, GLuint(fbo));
        glUseProgram(GLuint(program));
        glBindVertexArray(GLuint(vao));
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        glScissor(scissor_box[0], scissor_box[1], scissor_box[2], scissor_box[3]);
        set(GL_SCISSOR_TEST, scissor);
        set(GL_BLEND, blend);
        set(GL_DEPTH_TEST, depth);
        set(GL_CULL_FACE, cull);
    }
    static void set(GLenum cap, GLboolean on) {
        if (on) glEnable(cap); else glDisable(cap);
    }
};

}  // namespace

void ClipmapAtlas::bake(const std::vector<BakeRect>& rects, const BakeParams& p) {
    if (rects.empty() || !shader_) return;
    SavedState saved;

    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo_);
    glViewport(0, 0, kLevelSize, kBandRows * levels_);
    glEnable(GL_SCISSOR_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(vao_);

    const Shader& sh = *shader_;
    sh.use();
    sh.set_vec3("u_A", p.anchor.A);
    sh.set_vec3("u_E", p.anchor.E);
    sh.set_vec3("u_N", p.anchor.N);
    sh.set_float("u_R", p.anchor.R);
    sh.set_int("u_type", static_cast<int>(p.type));
    glUniform1ui(glGetUniformLocation(sh.program(), "u_seed"), p.seed);
    sh.set_float("u_scale", p.scale);

    const TypeParams& t = p.params;
    sh.set_float("u_p_base_wavelength_gu", t.base_wavelength_gu);
    sh.set_int("u_p_max_octaves", t.max_octaves);
    sh.set_float("u_p_gain", t.gain);
    sh.set_float("u_p_ridged", t.ridged);
    sh.set_float("u_p_amplitude", t.amplitude);
    sh.set_float("u_p_bump", t.bump);
    sh.set_float("u_p_albedo", t.albedo);
    sh.set_float("u_p_roughness", t.roughness);
    sh.set_float("u_p_roughness_var", t.roughness_var);
    sh.set_float("u_p_crack_width", t.crack_width);
    sh.set_float("u_p_stretch", t.stretch);
    sh.set_float("u_p_warp", t.warp);
    sh.set_float("u_p_gas_rate_gups", t.gas_rate_gups);
    sh.set_float("u_p_gas_period_s", t.gas_period_s);
    sh.set_float("u_p_coast_k", t.coast_k);
    sh.set_float("u_p_coast_a", t.coast_a);

    int bound_level = -1;
    for (const BakeRect& r : rects) {
        if (r.level < 0 || r.level >= levels_ || r.w <= 0 || r.h <= 0) continue;
        if (r.level != bound_level) {
            bound_level = r.level;
            sh.set_float("u_ts", p.ts0_gu * static_cast<float>(1 << r.level));
            const int oct = r.level < static_cast<int>(p.octaves_per_level.size())
                                ? p.octaves_per_level[r.level] : 1;
            sh.set_int("u_oct", oct);
        }
        const int row = r.level * kBandRows + r.band_row;
        glScissor(r.tor_x, row, r.w, r.h);
        sh.set_vec2("u_abs", glm::vec2(static_cast<float>(r.abs_x), static_cast<float>(r.abs_y)));
        sh.set_vec2("u_tor", glm::vec2(static_cast<float>(r.tor_x), static_cast<float>(row)));
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }
}

}  // namespace renderer::planet_detail
