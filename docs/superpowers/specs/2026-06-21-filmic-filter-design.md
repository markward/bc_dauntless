# Filmic Filter (Modern VFX) — Design

**Date:** 2026-06-21
**Status:** Approved, pending implementation plan

## Summary

A single **"Filmic Filter"** toggle under the existing **Modern VFX** config
group that applies three display-space post-process effects to the **main
exterior space view only**:

- **Film grain** — animated luma-weighted noise
- **Vignette** — smooth radial corner darkening
- **Chromatic aberration** — radial R/B channel separation

Default **on** (matching the rest of the Modern VFX group), not persisted across
launches (matching current dev/config toggles). One on/off row with effect
strengths fixed as tuned-by-feel constants in the shader — no sliders.

**Out of scope:** Motion blur is explicitly deferred to a separate spec
(camera-reconstruction vs. full velocity-buffer was the dominant cost driver and
is being handled on its own). Bridge interior, the bridge viewscreen inset, comm
sets, and the Ship Property Viewer are unaffected.

## Motivation

The Modern VFX group already offers HDR, Fresnel rim, decals, and procedural sky
as discrete neutral-modern toggles. A filmic grade (grain + vignette + CA) is a
stronger, more cinematic stylistic layer for the exterior flying view. The three
v1 effects each sample only the current frame's pixel neighborhood, so they are a
single cheap fullscreen fragment shader with no changes to the geometry passes.

## Architecture

### A dedicated final post-process pass

A new `FilmicPass` mirrors the existing `ResolvePass` / `SmaaPass` convention:

- Fullscreen triangle (`[-1,3]²` clipspace), VAO + static VBO.
- Embedded shader compiled at construction. Reuses the existing fullscreen-
  triangle vertex shader (`resolve.vert` / `SHADER_RESOLVE_VS`); only a new
  `filmic.frag` is added.
- `draw(std::uint32_t src_tex, GLuint dest_fbo, int w, int h)` signature, same
  shape as `SmaaPass::draw`. Sets its own viewport.

### Position in the pipeline

The filmic pass runs **last in the post chain**, after tonemap **and** after
SMAA, because grain / chromatic aberration / vignette belong in final display
space. Running them before SMAA would make edge detection chase animated grain
and the colored CA fringes.

```
scene → bloom → resolve(tonemap+grade) → SMAA → FILMIC → CEF composite
```

### Routing

Routing changes **only** when filmic is on **and** the current view is exterior
(`!viewer_mode && !bridge_active`):

| Case | resolve writes | SMAA writes | filmic writes |
|---|---|---|---|
| Filmic on, SMAA on | `g_ldr_target` | `g_ldr_target2` (new) | backbuffer |
| Filmic on, SMAA off | `g_ldr_target` | — | backbuffer (reads `g_ldr_target`) |
| Filmic off (any view) | unchanged from today | unchanged | not invoked |
| Bridge / viewer / viewscreen view | unchanged from today | unchanged | not invoked |

`g_ldr_target2` (RGBA8) is allocated only for the SMAA+filmic case (lazily, on
first use). When filmic is off, or for any non-exterior view, the routing and
output are **byte-identical to today** — the filmic pass is never invoked and
`g_ldr_target2` is never bound. The production render path for bridge / comm /
viewscreen / hologram views is untouched.

### Gating to exterior only

Reuses the existing `frame()` view flags. The filmic pass is invoked only when
`!viewer_mode && !bridge_active`. The bridge viewscreen inset (its own
`g_viewscreen_hdr` RTT path) is **not** filtered — "exterior view" here means the
main space view you fly in, not exterior content composited inside the bridge.

## The three effects

All three live in one `filmic.frag`. Strengths are named `const float` at the top
of the shader for easy tuning by feel. Final values are tuned during
implementation; starting points:

- **Film grain** — hash-based noise from screen UV plus an **elapsed-time
  uniform** (`u_time`) so the grain shifts each frame rather than freezing.
  Luma-weighted toward midtones (less in deep shadows / blown highlights).
  Strength ~0.03–0.05.
- **Vignette** — `smoothstep` radial darkening from screen center, ~0.25 at the
  corners, zero at center.
- **Chromatic aberration** — R and B channels sampled at UV offsets that scale
  radially from the center (zero at center, ~1–2 px at the corners); G unshifted.

The pass needs `u_time` (elapsed seconds) supplied each frame from the host's
existing frame-time bookkeeping.

## Toggle plumbing

Mirrors the Procedural Sky toggle (commit `a727a376`) end to end:

- **C++ flag** — `namespace dauntless_filmic { bool g_filmic_enabled = true;
  bool enabled(); void set_enabled(bool); }` in `frame.cc` (default **on**).
- **Binding** — `m.def("filmic_set_enabled", ...)` in `host_bindings.cc`.
- **Python wrapper** — `set_filmic_enabled(enabled)` in `engine/renderer.py`.
- **Applier wiring** — `set_filmic` applier created and passed to the config
  panel in `host_loop.py`.
- **Config UI** — `("ctrl", "filmic")` focusable in `configuration_panel.py`
  within the Modern VFX group, a `toggle:filmic` handler, a `filmic_on` settings
  field (default `True`), and the matching CEF row (HTML + JS) labelled
  "Filmic Filter".

## Build notes

- New `filmic.frag` is embedded via `embed_shader()` in
  `native/src/renderer/CMakeLists.txt`.
- Shader changes require a `cmake -B build -S .` reconfigure before
  `cmake --build` (embedded shaders are regenerated at configure time).
- `host_bindings.cc` edits require a full `dauntless` rebuild (compiled into both
  the binary and the `_dauntless_host` module).

## Testing

- **C++ frame test** — the filmic pass runs GL-error-free; its output differs
  from its input when enabled; and when disabled (or when `bridge_active`) the
  pass is not invoked and output is exact passthrough.
- **Python test** — `set_filmic_enabled()` reaches the binding; the config panel
  exposes the `filmic` toggle and `toggle:filmic` flips `filmic_on`. Mirrors the
  existing procedural-sky toggle tests.

## Decisions captured

- Single toggle, fixed strengths (no per-effect toggles, no sliders).
- Default **on**, not persisted.
- Dedicated final pass over folding filmic math into `resolve.frag`, for correct
  ordering relative to SMAA.
- Bridge viewscreen inset excluded.
- Motion blur deferred to its own spec.
