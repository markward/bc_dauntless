# Motion Blur (Modern VFX) — Design

**Date:** 2026-06-21
**Status:** Approved, pending implementation plan
**Relates to:** [Filmic Filter](2026-06-21-filmic-filter-design.md) (deferred motion blur to this spec)

## Summary

A **"Motion Blur"** toggle under the Modern VFX config group (default **on**,
not persisted) that applies **camera motion blur** to the **main exterior view
only**, via a dedicated post-process pass. The frame smears based on how the
camera moved between frames — turning, banking, dollying, accelerating, warp.
Per-object motion (a ship streaking across a still camera) is explicitly **out
of scope** (that needs a per-object velocity buffer touching every geometry
shader; not pursued).

## Technique — depthless fixed-distance reprojection

The HDR scene target's depth is a renderbuffer, not a sampleable texture, so we
deliberately avoid depth-based reconstruction (which would require changing the
core scene FBO). Instead, per pixel:

1. Reconstruct a view-space ray from the inverse projection at the pixel's NDC:
   `ray_view = normalize((inverse(proj) * vec4(ndc.xy, -1, 1)).xyz)`.
2. Place a pseudo–world point at a fixed distance **D** along it:
   `p_world = u_cam_pos + u_distance_gu * (u_cam_rot * ray_view)`
   (`u_cam_rot` is the current camera view→world rotation, mat3).
3. Reproject through the **previous frame's** view-projection:
   `clip_prev = u_prev_viewproj * vec4(p_world, 1)`,
   `uv_prev = (clip_prev.xy / clip_prev.w) * 0.5 + 0.5`.
4. Motion vector `mv = (uv - uv_prev) * u_strength`, with its length clamped to
   `u_max_uv`.
5. Sample N taps of the scene color along `[uv - mv … uv]` and average.

Properties:
- **Rotation** (turn/bank) reprojects correctly for any D — the dominant
  space-sim case.
- **Translation** (dolly/warp/accel) blurs as if the scene sits at distance D,
  producing the radial speed-streak. D is a live-tunable constant in **game
  units (GU)**; very-near-object parallax is the accepted approximation.
- Reprojecting against *last frame's* matrix makes `mv` inherently per-frame, so
  blur scales with how fast the view actually moved; `u_max_uv` caps a hard
  view-snap from smearing the whole screen.

### Uniforms

| Uniform | Source |
|---|---|
| `u_src` | scene color (the current ping-pong input) |
| `u_inv_proj` (mat4) | `inverse(camera.proj_matrix())` |
| `u_cam_rot` (mat3) | camera view→world rotation (from `inverse(view)`) |
| `u_cam_pos` (vec3) | camera world position |
| `u_prev_viewproj` (mat4) | cached previous-frame `proj · view` |
| `u_distance_gu` (float) | `kMotionBlurDistanceGU` |
| `u_strength` (float) | `kMotionBlurStrength` |
| `u_samples` (int) | `kMotionBlurSamples` |
| `u_max_uv` (float) | `kMotionBlurMaxUV` |

### Host-side state

- Cache `glm::mat4 g_prev_viewproj` plus a `bool g_have_prev_viewproj`. Each
  exterior frame: compute the motion vectors using the cached value, render the
  pass, then store the current `proj · view` for next frame.
- First frame, or the first frame after the toggle/exterior becomes active,
  has no valid previous matrix → the pass is skipped (passthrough), avoiding a
  one-frame garbage smear.

### Tunable constants (named, live-tunable like the filmic grade)

- `kMotionBlurStrength` — motion-vector multiplier. Start ~`1.0`.
- `kMotionBlurSamples` — taps along the vector. Start `8`.
- `kMotionBlurMaxUV` — max motion-vector length in UV (fraction of screen).
  Start ~`0.05` (caps view-snap smear).
- `kMotionBlurDistanceGU` — assumed scene distance for translation parallax.
  Start ~`100.0` GU (tune by feel; BC ships sit tens–hundreds of GU out).

## Pipeline placement + routing refactor

New order: `scene → bloom → resolve(tonemap) → SMAA → motion blur → filmic →
backbuffer`. Motion blur sits with the image content, below filmic's grain /
vignette / CA (which remain the topmost "lens" layer and must not be smeared).

This makes **three** optional LDR passes in series (SMAA, motion blur, filmic).
The current routing hand-cases SMAA×filmic; with three passes that becomes
combinatorial. Refactor it into a **ping-pong**:

- resolve always runs first (HDR→LDR).
- If **no** optional pass is active, resolve writes straight to the backbuffer —
  the existing zero-cost path, preserved byte-for-byte.
- Otherwise resolve writes to LDR target **A**; each active optional pass, in
  order, reads the current target and writes the other (A⇄B); the **last**
  active pass writes the backbuffer (fbo 0).
- Two LDR targets cover any number of passes (`g_ldr_target` = A,
  `g_ldr_target2` = B, both already present).

Each optional pass exposes a uniform `draw(src_tex, dst_fbo, w, h, …)` shape so
the ping-pong driver treats them uniformly.

## Toggle, scope, plumbing

- Own **"Motion Blur"** row in the Modern VFX group, **separate** from Filmic,
  default **on**, not persisted. Plumbing mirrors the procedural-sky/filmic
  pattern end to end:
  - C++ flag: `namespace dauntless_motion_blur { bool g_enabled = true;
    enabled(); set_enabled(bool); }` in `frame.cc`.
  - Bindings: `motion_blur_set_enabled` + `motion_blur_enabled` in
    `host_bindings.cc`.
  - Python: `engine.renderer.set_motion_blur_enabled` / `motion_blur_enabled`.
  - Config UI: `("ctrl","motion_blur")` focusable + `toggle:motion_blur`
    handler + `motion_blur_on` setting (default `True`) + CEF row "Motion Blur".
    Appended after `filmic` in both the Python focus list and the CEF list so
    keyboard nav stays in sync.
  - host_loop: initial `motion_blur_on=r.motion_blur_enabled()` snapshot +
    `set_motion_blur=r.set_motion_blur_enabled` applier.
- **Exterior-only**, same gate as filmic (`!viewer_mode && !bridge_active`);
  bridge interior and the viewscreen inset never blur.

## Components

- `renderer::MotionBlurPass` (`motion_blur_pass.{h,cc}`) — mirrors `FilmicPass`:
  fullscreen triangle, reuses `resolve.vert`, GL-state save/restore. New
  `motion_blur.frag` embedded via `embed_shader`.
- `dauntless_motion_blur` toggle namespace in `frame.cc`.
- Host globals: `g_motion_blur_pass`, `g_prev_viewproj`, `g_have_prev_viewproj`;
  the ping-pong routing in `frame()`.

## Testing

- Unit-test `dauntless_motion_blur` toggle (default on, round-trips) — mirrors
  `DauntlessFilmicToggle`.
- Unit-test a pure motion-vector helper: given prev/cur view-proj + camera and a
  pixel, the reprojected `uv_prev` matches a hand-computed value; a static
  camera (prev == cur) yields a ~zero vector → no blur. (Pure math, no GL.)
- GL pass test mirrors `FilmicPassTest`: runs GL-error-free; a synthetic
  `u_prev_viewproj` offset produces directional blur (output differs from
  input along the expected axis); first-frame / disabled = passthrough.
- Routing refactor verified by the existing `FilmicPassTest` / `ResolvePassTest`
  staying green (no regression to the SMAA/filmic/off paths) + live check.

## Decisions captured

- Camera motion only; per-object velocity buffer out of scope.
- Depthless fixed-distance reprojection (no core-FBO depth-texture change);
  D is a tunable GU constant.
- Own Motion Blur toggle, default on, not persisted, exterior-only.
- Post chain refactored to a 2-target ping-pong over the optional passes;
  no-optional-pass path stays byte-identical.
- Strengths/samples/distance/cap are named live-tunable constants.

## Out of scope

- Per-object / velocity-buffer motion blur.
- Depth-based parallax reconstruction.
- Motion blur on the bridge interior or the viewscreen inset.
