// native/src/renderer/bloom_pass.cc
//
// Dual-filter bloom pass (Jimenez "Next Generation Post Processing in COD:AW").
// Threshold prefilter → downsample mip chain → additive tent upsample.
// Returns the half-resolution bloom texture for compositing into the resolve
// pass before ACES tonemapping.

#include <renderer/bloom_pass.h>
#include <renderer/shader.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_bloom_prefilter_fs.h"
#include "embedded_bloom_down_fs.h"
#include "embedded_bloom_up_fs.h"

#include <glm/glm.hpp>

namespace {
static constexpr int kMaxMips  = 6;  // maximum mip levels in the bloom chain
static constexpr int kMinMipDim = 8; // stop halving when next level would be < this
}  // namespace

namespace renderer {

BloomPass::BloomPass()
    : prefilter_(std::make_unique<Shader>(shader_src::resolve_vs,
                                          shader_src::bloom_prefilter_fs)),
      down_(std::make_unique<Shader>(shader_src::resolve_vs,
                                     shader_src::bloom_down_fs)),
      up_(std::make_unique<Shader>(shader_src::resolve_vs,
                                   shader_src::bloom_up_fs)) {
    // Fullscreen-triangle: one triangle covering [-1,3]² clipspace.
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

BloomPass::~BloomPass() {
    destroy();
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
    // prefilter_, down_, up_ are unique_ptr — auto-cleaned.
}

void BloomPass::draw_quad() {
    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
}

void BloomPass::destroy() {
    for (auto& m : mips_) {
        if (m.tex) glDeleteTextures(1, &m.tex);
        if (m.fbo) glDeleteFramebuffers(1, &m.fbo);
    }
    mips_.clear();
    fw_ = 0;
    fh_ = 0;
}

void BloomPass::rebuild(int fw, int fh) {
    destroy();

    // mip[0] = half-res, each subsequent = half down to min dimension >= kMinMipDim,
    // capped at kMaxMips mips.
    int w = fw / 2;
    int h = fh / 2;
    if (w < 1) w = 1;
    if (h < 1) h = 1;

    while (true) {
        Mip m;
        m.w = w;
        m.h = h;

        glGenTextures(1, &m.tex);
        glBindTexture(GL_TEXTURE_2D, m.tex);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0,
                     GL_RGBA, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);

        glGenFramebuffers(1, &m.fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, m.fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, m.tex, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);

        mips_.push_back(m);

        // Stop if we've reached the cap or the next halving would be < kMinMipDim.
        if (static_cast<int>(mips_.size()) >= kMaxMips) break;
        int nw = w / 2;
        int nh = h / 2;
        if (nw < kMinMipDim || nh < kMinMipDim) break;
        w = nw;
        h = nh;
    }

    fw_ = fw;
    fh_ = fh;
}

std::uint32_t BloomPass::render(std::uint32_t hdr_color_tex, int fw, int fh) {
    if (fw != fw_ || fh != fh_ || mips_.empty()) {
        rebuild(fw, fh);
    }

    const int N = static_cast<int>(mips_.size());

    // Save blend and depth-test state.
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    // ── Prefilter: HDR → mip[0] ────────────────────────────────────────────
    glBindFramebuffer(GL_FRAMEBUFFER, mips_[0].fbo);
    glViewport(0, 0, mips_[0].w, mips_[0].h);
    prefilter_->use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_color_tex);
    prefilter_->set_int("u_src", 0);
    prefilter_->set_float("u_threshold", threshold_);
    draw_quad();

    // ── Downsample: mip[i-1] → mip[i] ─────────────────────────────────────
    for (int i = 1; i < N; ++i) {
        glBindFramebuffer(GL_FRAMEBUFFER, mips_[i].fbo);
        glViewport(0, 0, mips_[i].w, mips_[i].h);
        down_->use();
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, mips_[i - 1].tex);
        down_->set_int("u_src", 0);
        down_->set_vec2("u_texel",
                        glm::vec2(1.0f / static_cast<float>(mips_[i - 1].w),
                                  1.0f / static_cast<float>(mips_[i - 1].h)));
        draw_quad();
    }

    // ── Upsample (additive): mip[i] → mip[i-1] ────────────────────────────
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);

    for (int i = N - 1; i > 0; --i) {
        glBindFramebuffer(GL_FRAMEBUFFER, mips_[i - 1].fbo);
        glViewport(0, 0, mips_[i - 1].w, mips_[i - 1].h);
        up_->use();
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, mips_[i].tex);
        up_->set_int("u_src", 0);
        up_->set_vec2("u_texel",
                      glm::vec2(1.0f / static_cast<float>(mips_[i].w),
                                1.0f / static_cast<float>(mips_[i].h)));
        draw_quad();
    }

    glDisable(GL_BLEND);
    // reset to pipeline-default blend func (we changed it to additive for upsample)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    // Restore state.
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);

    return mips_[0].tex;
}

}  // namespace renderer
