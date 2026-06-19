# FXAA → SMAA 1x — Design

**Date:** 2026-06-20
**Status:** Approved (design); implementation pending
**Scope:** Replace the current FXAA post-process anti-aliasing with SMAA 1x, and expose an Off/On control under Settings > Configuration > Graphics.

## Purpose

The renderer's only anti-aliasing today is **FXAA** — a single-pass spatial edge
filter ([fxaa_pass.cc](../../../native/src/renderer/fxaa_pass.cc),
[fxaa.frag](../../../native/src/renderer/shaders/fxaa.frag)), run as the final
LDR post-pass after tonemapping. FXAA is cheap but soft and prone to
edge-crawling. **SMAA 1x** produces noticeably sharper, more stable edges for a
small cost (~+0.5 ms, two extra fullscreen passes, two small lookup textures) and
— critically — sits in the **same place in the pipeline** as FXAA: post-tonemap,
LDR, no HDR-side or pass-order changes.

This pass deliberately stays **spatial only** (SMAA 1x). The temporal and
MSAA-based SMAA variants are explicitly out of scope (see below) because they
would reintroduce the motion-vector / history-buffer / MSAA machinery that the
"cheap upgrade" rationale exists to avoid.

## Decisions

- **FXAA is removed entirely**, not left as dead code or a fallback option. The
  AA control is a simple Off/On toggle (On = SMAA 1x), matching the existing
  toggle widgets. Default: **On**.
- **Lookup textures are embedded in the binary** as byte-array C headers (from
  the SMAA reference implementation, MIT-licensed), not shipped as asset files.
  ~90 KB total; avoids any runtime file-loading path.
- **Session-only**, not persisted across launches — consistent with every other
  setting in the configuration panel.

## Background: why SMAA 1x and not "2X/4X"

SMAA's "1x / S2x / T2x / 4x" are *different techniques*, not quality multipliers:

- **SMAA 1x** — pure spatial post-process. This design. ~+0.5 ms, no new
  framebuffers beyond two small intermediates.
- **SMAA S2x** — requires rendering into a 2× **MSAA** target + resolve. Real
  memory/bandwidth cost and pipeline rework. Out of scope.
- **SMAA T2x** — **temporal**: needs camera jitter + motion vectors + a history
  buffer (i.e. the TAA pipeline). Out of scope.
- **SMAA 4x** — S2x + T2x combined. Out of scope.

## Architecture

### Pass structure

SMAA 1x is three fullscreen passes. It slots into the exact slot FXAA occupies —
after the resolve pass writes LDR into `LdrTarget`, before the CEF composite:

```
scene → HdrTarget (RGBA16F)
bloom (optional, HDR)
resolve/tonemap → LdrTarget (RGBA8, color)        [unchanged]
SMAA (when enabled):
  Pass 1  edge detection:    LdrTarget                         → edges RT   (RG8)
  Pass 2  blend-weight calc: edges + AreaTex + SearchTex       → weights RT (RGBA8)
  Pass 3  neighborhood blend: LdrTarget + weights             → backbuffer
SMAA (when disabled): resolve writes straight to backbuffer    [as today with FXAA off]
CEF composite (overlay UI)
swap buffers
```

Edge detection is **luma-based** (cheaper than color edges, and adequate). The
input is the tonemapped LDR color, which is perceptual/gamma-encoded — exactly
what SMAA's luma edge detection expects. This is also why SMAA sits post-tonemap,
identical to where FXAA sits.

### New component: `SmaaPass`

Mirrors the existing `FxaaPass` class structure
([fxaa_pass.h](../../../native/src/renderer/include/renderer/fxaa_pass.h),
[fxaa_pass.cc](../../../native/src/renderer/fxaa_pass.cc)):

- Owns: fullscreen-triangle VAO/VBO, three shader programs (one per pass), two
  intermediate render targets (`edges` RG8, `weights` RGBA8), and the two lookup
  textures (AreaTex, SearchTex).
- `SmaaPass::draw(GLuint ldr_color_tex, GLuint dest_fbo, int width, int height)`
  runs the three passes, binding `dest_fbo` (the backbuffer) for the final blend.
- `resize(w, h)` (re)allocates the two intermediate RTs, matching the
  `HdrTarget::resize` / `LdrTarget::resize` pattern.
- Lookup textures uploaded once at construction via `glTexImage2D`
  (AreaTex: RG8 160×560; SearchTex: R8 64×16).

The intermediate RTs and lookup textures are well-bounded inside `SmaaPass`; no
other renderer code needs to know SMAA is three passes rather than one.

### Shaders

Three new GLSL shaders under
[native/src/renderer/shaders/](../../../native/src/renderer/shaders/), adapted
from the SMAA reference single-header port to our **GL 4.1 core** target (macOS):

- `smaa_edge.vert` / `smaa_edge.frag` — luma edge detection.
- `smaa_weight.vert` / `smaa_weight.frag` — blend-weight calculation (samples
  AreaTex + SearchTex).
- `smaa_blend.vert` / `smaa_blend.frag` — neighborhood blending.

Each pass needs the SMAA macro setup (resolution / `SMAA_RT_METRICS`, preset).
Reminder: shader changes require a `cmake` reconfigure before
`cmake --build` (see memory: shader edits aren't picked up by build alone).

### Lookup textures

Embedded as C headers (`area_tex.h`, `search_tex.h`) holding the reference
byte arrays under [native/src/renderer/](../../../native/src/renderer/). MIT
license header retained. No asset files, no loader.

## Config UI

The configuration panel already has an FXAA toggle in the "Modern VFX" group; the
change is a rename + relabel, not a new widget.

### Python — [engine/ui/configuration_panel.py](../../../engine/ui/configuration_panel.py)

- `SettingsSnapshot.fxaa_on: bool = True` → `smaa_on: bool = True`.
- Dispatch `toggle:fxaa` → `toggle:smaa`; applier calls
  `renderer.set_smaa_enabled(...)`.
- Keyboard nav focus target `"fxaa"` → `"smaa"` (focusable list + activation
  branch).

### Renderer wrapper — [engine/renderer.py](../../../engine/renderer.py)

- `set_fxaa_enabled` → `set_smaa_enabled`, calling the renamed host binding
  `_h.smaa_set_enabled(...)`.

### Host bindings — [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc)

- `g_fxaa_enabled` → `g_smaa_enabled` (default `true`); `fxaa_set_enabled`
  binding → `smaa_set_enabled`; the `frame()` post-chain calls `SmaaPass::draw`
  in place of `FxaaPass::draw`.
- Reminder: `host_bindings.cc` is compiled into both the `dauntless` binary and
  the `_dauntless_host` module — rebuild `dauntless`, not just the module
  (see memory: host_bindings build target).

### CEF — [native/assets/ui-cef/js/configuration_panel.js](../../../native/assets/ui-cef/js/configuration_panel.js)

- Relabel the row "FXAA" → "Anti-Aliasing (SMAA)", event
  `configuration/toggle:fxaa` → `configuration/toggle:smaa`, state field
  `s.fxaa_on` → `s.smaa_on`. Reuses the existing `cp-toggle` widget — no new CSS.
  CEF JS changes need no rebuild.

## Removal of FXAA

Delete `fxaa_pass.{h,cc}`, `fxaa.vert`, `fxaa.frag`, the CMake references, and the
`g_fxaa_enabled` / `fxaa_set_enabled` plumbing. No FXAA code remains.

## Testing (TDD)

- **C++ `FrameTest`** (gtest in `native/tests/`): the SMAA pass runs
  GL-error-free and produces non-black output on a known scene (mirrors how the
  existing frame tests exercise post passes). A targeted check that an aliased
  edge in the input is softened in the output is a stretch goal; the primary
  guarantee is "runs clean, three passes execute, lookup textures bind."
- **Python**: configuration-panel round-trip test — dispatching `toggle:smaa`
  flips `SettingsSnapshot.smaa_on` and invokes the applier (mockable; no GL
  context needed). Replaces/renames the existing FXAA toggle test if present.

## Out of scope

- Persistence of the setting across launches.
- SMAA S2x (MSAA), SMAA T2x / 4x (temporal).
- Motion/velocity vectors, camera jitter, history buffers, TAA.
- Any HDR-side or pass-order changes (SMAA reuses FXAA's slot).

## Effort

~1 focused session: new `SmaaPass` + three shaders + two embedded lookup
textures, a rename pass across the config UI plumbing, FXAA removal, and the two
tests.
