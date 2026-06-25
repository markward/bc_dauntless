# Resolution-scaled film grain

**Date:** 2026-06-25
**Status:** Approved, implementing

## Problem

The filmic post-process grain (`native/src/renderer/shaders/filmic.frag`) looks
right on a high-DPI retina display but reads as **overpowered on a lower-resolution
HD screen**. The grain grid is hardcoded:

```glsl
float n = hash(uv * vec2(1920.0, 1080.0) + fract(u_time) * 100.0) - 0.5;
col += n * GRAIN_STRENGTH * midweight;   // GRAIN_STRENGTH = 0.15
```

`uv` is normalized 0–1, so the grain is a fixed 1920×1080 cell grid regardless of
the real framebuffer. This is **not** aliasing — on a 1080p HD monitor it lands at
exactly 1 cell/pixel at full `0.15` amplitude, and because each physical pixel is
large the fixed amplitude reads as harsh. On a retina backing store (~2880×1800)
the same amplitude on physically tiny pixels reads as subtle and correct.

Framebuffer height is a good automatic proxy: retina backing stores are tall, HD
ones are not. `FilmicPass::draw()` already receives the framebuffer height `fh`.

## Approach

Chosen: **amplitude attenuation keyed on framebuffer height** (preserves the
retina look exactly; only attenuates downward on lower-resolution screens).

Rejected alternatives:
- Switching the grain grid to `gl_FragCoord` (true per-pixel). More textbook-correct
  and kills the hardcoded 1920×1080, but it *changes* the approved retina appearance
  and needs re-tuning. YAGNI.
- Plumbing GLFW content-scale / DPI down to the pass. Semantically cleaner
  "retina vs HD" signal but needs new window→pass plumbing; framebuffer height
  already captures it in the common case.

## Design

Scale grain **amplitude only**. The grain grid, character, and midtone weighting
are unchanged.

### `filmic.frag`

Add a framebuffer-height uniform and two eye-tunable consts alongside the existing
grade consts:

```glsl
uniform float u_fb_height;                 // backing-store height in px
const float GRAIN_REF_HEIGHT = 1800.0;     // at/above this, grain stays full
const float GRAIN_FLOOR      = 0.4;        // never drop below 40% grain
```

Fold a clamped scale factor into the grain term:

```glsl
float grain_scale = clamp(u_fb_height / GRAIN_REF_HEIGHT, GRAIN_FLOOR, 1.0);
col += n * GRAIN_STRENGTH * grain_scale * midweight;
```

### `filmic_pass.cc`

One line in `draw()` (it already has `fh`):

```cpp
shader_->set_float("u_fb_height", static_cast<float>(fh));
```

## Behavior

| Backing height | grain_scale | Note |
|---|---|---|
| ≥ 1800px (retina) | 1.0× | identical to today |
| 1440px | 0.8× | |
| 1080px (HD) | 0.6× | the overpowered case, softened |
| ≤ 720px | 0.4× | floored |

Linear falloff between the floor and the reference; clamped at 1.0 so ultra-high
resolutions never boost grain above today's value. Cost is one `clamp` per
fragment plus one uniform set per frame.

## Verification

- Shader edits require a `cmake -B build -S .` reconfigure before `--build`
  (project shader-rebuild rule), then `cmake --build build -j`.
- Run the full gate `scripts/check_tests.sh` (pytest + ctest). If any `FrameTest`
  renders the filmic pass at a non-1800 height its golden image shifts; handle
  that within this change rather than treating it as pre-existing.
