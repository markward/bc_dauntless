// native/src/renderer/nonfinite_probe.cc
//
// Two-stage max-reduction that answers "did any texel of this render target
// hold a NaN or an Inf, and roughly where". See renderer/nonfinite_probe.h.

#include <renderer/nonfinite_probe.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_nonfinite_probe_fs.h"

namespace {
// Source texels per intermediate texel. 8x8 gives the first pass plenty of
// fragments to work with (32k at 1080p) while cutting the second pass's job to
// a handful of taps per cell.
constexpr int kCoarseBlock = 8;

int ceil_div(int a, int b) { return (a + b - 1) / b; }
}  // namespace

namespace renderer {

NonfiniteProbe::NonfiniteProbe()
    : shader_(std::make_unique<Shader>(shader_src::resolve_vs,
                                       shader_src::nonfinite_probe_fs)) {
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

    result_.grid.assign(static_cast<std::size_t>(kGridW) * kGridH, 0);
}

NonfiniteProbe::~NonfiniteProbe() {
    destroy();
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void NonfiniteProbe::destroy() {
    for (Target* t : {&coarse_, &grid_}) {
        if (t->tex) glDeleteTextures(1, &t->tex);
        if (t->fbo) glDeleteFramebuffers(1, &t->fbo);
        *t = Target{};
    }
    fw_ = 0;
    fh_ = 0;
}

void NonfiniteProbe::rebuild(int fw, int fh) {
    destroy();

    coarse_.w = ceil_div(fw, kCoarseBlock);
    coarse_.h = ceil_div(fh, kCoarseBlock);
    if (coarse_.w < 1) coarse_.w = 1;
    if (coarse_.h < 1) coarse_.h = 1;
    grid_.w = kGridW;
    grid_.h = kGridH;

    for (Target* t : {&coarse_, &grid_}) {
        glGenTextures(1, &t->tex);
        glBindTexture(GL_TEXTURE_2D, t->tex);
        // R8 is enough: every value written is 0.0 or 1.0.
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, t->w, t->h, 0,
                     GL_RED, GL_UNSIGNED_BYTE, nullptr);
        // NEAREST throughout — the reduction uses texelFetch, and any filtering
        // here would blur the position we are trying to recover.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);

        glGenFramebuffers(1, &t->fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, t->fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, t->tex, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    fw_ = fw;
    fh_ = fh;
}

void NonfiniteProbe::draw_quad() {
    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);
}

void NonfiniteProbe::reduce(std::uint32_t src_tex, const Target& dst,
                            int block_x, int block_y, bool detect) {
    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo);
    glViewport(0, 0, dst.w, dst.h);
    shader_->use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src_tex);
    shader_->set_int("u_src", 0);
    shader_->set_int("u_detect", detect ? 1 : 0);
    shader_->set_ivec2("u_block", glm::ivec2(block_x, block_y));
    draw_quad();
}

const NonfiniteProbe::Result& NonfiniteProbe::run(std::uint32_t src_tex,
                                                  int fw, int fh) {
    if (fw < 1 || fh < 1) return result_;
    if (fw != fw_ || fh != fh_ || coarse_.fbo == 0) rebuild(fw, fh);

    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    // The fullscreen triangle winds CCW and the Pipeline sets CW front-facing,
    // so it would be culled away. Blend must be off or the max-reduce turns into
    // an alpha blend against whatever was in the target.
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    // Stage 1: full-res -> 1/8, flagging non-finite RGB.
    reduce(src_tex, coarse_, kCoarseBlock, kCoarseBlock, /*detect=*/true);
    // Stage 2: 1/8 -> grid, max-reducing the flags.
    reduce(coarse_.tex, grid_, ceil_div(coarse_.w, kGridW),
           ceil_div(coarse_.h, kGridH), /*detect=*/false);

    // Readback. 576 bytes, but still a synchronous stall — the reason this
    // probe is opt-in. A PBO with a one-frame delay would remove the stall if
    // it ever needs to run continuously.
    glBindFramebuffer(GL_FRAMEBUFFER, grid_.fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, kGridW, kGridH, GL_RED, GL_UNSIGNED_BYTE,
                 result_.grid.data());

    result_.flagged_cells = 0;
    result_.max_code = 0;
    for (std::uint8_t v : result_.grid) {
        if (!v) continue;
        ++result_.flagged_cells;
        if (v > result_.max_code) result_.max_code = v;
    }
    result_.any = result_.flagged_cells > 0;

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);

    return result_;
}

}  // namespace renderer
