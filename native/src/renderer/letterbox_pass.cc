// native/src/renderer/letterbox_pass.cc
#include "renderer/letterbox_pass.h"

#include <glad/glad.h>

#include <algorithm>
#include <cmath>

namespace renderer::letterbox {
namespace {
// SOLE WRITER: engine/host_loop.py's _pump_letterbox, via set_covered()
// below. It runs unconditionally every frame (pushed before r.frame() is
// called each iteration of run()'s main loop), so this TU-static is
// re-established from Python state every tick and never needs an explicit
// reset on renderer shutdown/re-init -- unlike other process-statics in this
// codebase that have been bitten by surviving a GL context init/shutdown
// cycle (see docs re: GL context lifecycle hazards), there is no window
// where a stale value here could be read before the next frame's pump
// overwrites it.
float g_covered = 0.0f;
}  // namespace

void set_covered(float covered) {
    // fCoveredArea comes from mission script (StartCutscene(1.0,
    // float('nan')) is a real, if hostile, call). std::clamp's comparisons
    // are both false for NaN, so it would fall straight through unclamped
    // and later feed std::lround() an unspecified result in draw(). Reject
    // non-finite input before the clamp instead.
    if (!std::isfinite(covered)) covered = 0.0f;
    g_covered = std::clamp(covered, 0.0f, 1.0f);
}

float covered() { return g_covered; }

void draw(int fb_width, int fb_height) {
    if (g_covered <= 0.0f || fb_width <= 0 || fb_height <= 0) return;

    // Per-bar height: covered is the TOTAL fraction, split across two bars.
    const int bar = static_cast<int>(
        std::lround(static_cast<double>(g_covered) * 0.5 * fb_height));
    if (bar <= 0) return;

    // Save the state we touch. ui_cef::composite() (which runs right after
    // this pass) already disables GL_SCISSOR_TEST itself, so it is not at
    // risk from us — but it also RESTORES whatever scissor state was active
    // before it ran, so a leaked enabled+bar-sized scissor from this pass
    // would survive into the START of the NEXT frame and clip the early
    // glClear() calls on the shadow/viewscreen/HDR targets in
    // host_bindings.cc to the bar rectangle, leaving stale contents outside
    // it.
    GLfloat prev_clear[4];
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prev_clear);
    const GLboolean prev_scissor_enabled = glIsEnabled(GL_SCISSOR_TEST);
    GLint prev_box[4];
    glGetIntegerv(GL_SCISSOR_BOX, prev_box);
    GLint prev_viewport[4];
    glGetIntegerv(GL_VIEWPORT, prev_viewport);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, fb_width, fb_height);
    glEnable(GL_SCISSOR_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);

    // GL's origin is bottom-left, so y=0 is the BOTTOM bar.
    glScissor(0, 0, fb_width, bar);
    glClear(GL_COLOR_BUFFER_BIT);
    glScissor(0, fb_height - bar, fb_width, bar);
    glClear(GL_COLOR_BUFFER_BIT);

    if (!prev_scissor_enabled) glDisable(GL_SCISSOR_TEST);
    glScissor(prev_box[0], prev_box[1], prev_box[2], prev_box[3]);
    glClearColor(prev_clear[0], prev_clear[1], prev_clear[2], prev_clear[3]);
    // Restore the viewport too, purely for symmetry with the rest of the
    // saved state above. Leaving it at (0,0,fb_width,fb_height) would in
    // practice be harmless: every post-process pass and the CEF composite
    // that run after this one set their own viewport before drawing.
    glViewport(prev_viewport[0], prev_viewport[1], prev_viewport[2], prev_viewport[3]);
}

}  // namespace renderer::letterbox
