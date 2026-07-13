// native/src/renderer/include/renderer/letterbox_pass.h
#pragma once

/// Cutscene letterbox bars.
///
/// Drawn by the renderer rather than by CEF so that the entire UI overlay
/// composites ON TOP of the bars by construction — no z-index to forget. The
/// bars used to be DOM (`.sdk-letterbox`, z-index 5) and swallowed any HUD
/// root that had no z-index of its own, which is how E1M1's XO menu once went
/// invisible mid-tutorial.
///
/// Called from host_bindings::frame() after the post-process chain has
/// resolved into FBO 0 and before ui_cef::composite().
///
/// Spec: docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
namespace renderer::letterbox {

/// Set the TOTAL covered fraction (BC's fCoveredArea: 0.125 => 6.25% per
/// bar). Clamped to [0, 1] — the value originates in mission script.
void set_covered(float covered);

/// Current total covered fraction, in [0, 1].
float covered();

/// Draw the two bars into FBO 0. No-op when the coverage is zero, so an
/// out-of-cutscene frame costs one float compare.
///
/// Saves and restores GL_SCISSOR_TEST/GL_SCISSOR_BOX. ui_cef::composite()
/// (which runs right after this pass each frame) already disables
/// GL_SCISSOR_TEST itself, so a leak from here would NOT clip that overlay
/// draw — but composite() also RESTORES whatever scissor state was active
/// before it ran, so a leaked enabled+bar-sized scissor would survive into
/// the START of the next frame and clip the shadow/viewscreen/HDR target
/// glClear() calls in host_bindings.cc to the bar rectangle.
void draw(int fb_width, int fb_height);

}  // namespace renderer::letterbox
