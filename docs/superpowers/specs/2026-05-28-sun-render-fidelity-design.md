# Sun Render Fidelity — Design

**Date:** 2026-05-28
**Status:** Approved (brainstorming) — pending implementation plan.

## Problem

Our current sun rendering shows a chunky polygonal corona shell roughly 4× the body radius. In BC the same scene reads as a bright textured disc with a thin halo and a much larger lens-flare-driven outer glow. The mismatch comes from two compounding errors:

1. The renderer treats `atmosphere_thickness` (an SDK gameplay parameter, the AI damage-zone radius — only consumer is `sdk/Build/scripts/AI/PlainAI/Intercept.py:283`) as a visual corona radius. The corona aggregator emits `corona_radius = (body_radius + atmosphere_thickness)`, and since every SDK call passes `atmosphere_thickness == body_radius`, that gives a 2× shell radius before any fudge.
2. `sun_pass.cc` then applies hardcoded `kBodyVisualScale = 2.0` and `kCoronaVisualScale = 2.0` multipliers on top of that, so the on-screen corona is ~4× the SDK body radius.

A second gap: BC's engine renders an animated wispy overlay (the `SunEffect` node textured with `flare_texture`, e.g. `Effects/SunFlaresYellow.tga`). The 5th argument to `App.Sun_Create` carries this texture, and our aggregator stashes it on `_flare_texture`, but the renderer never sees it. The visual bulk and motion BC supplies via that overlay is missing entirely in our build.

## Goal

Match BC's sun appearance closely enough that side-by-side screenshots read the same: bright textured body, a thin soft halo right next to it, an animated wispy overlay extending modestly beyond, and the existing lens flare unchanged.

`atmosphere_thickness` must stop reaching the renderer. It is gameplay-only.

## Non-goals

- LensFlares.py and `lens_flare_pass.cc` are not touched in this pass. If the at-source `rays` halo reads weak after the new overlay lands, that becomes a follow-up.
- No turbulence/noise-warp overlay variants; only the simplest BC-faithful single rotating billboard.
- No per-sun authoring controls beyond what the SDK already provides (`base_texture`, `flare_texture`).

## Visual composition

Each sun renders as four stacked layers:

| Layer | Geometry | Blend | Source |
|---|---|---|---|
| 1. Body | front-culled UV sphere at `body_radius` | opaque | `base_texture` |
| 2. Corona shell | back-culled UV sphere at `body_radius * 1.1` | additive | `base_texture`, equator alpha = `sin(v.y · π) · 0.54` |
| 3. Flare overlay (new) | camera-facing additive quad, half-size `body_radius * 1.5` | additive | `flare_texture`, UVs rotated around `(0.5, 0.5)` at ~5°/s |
| 4. Lens flare | existing pass — unchanged | — | `Tactical.LensFlares.*` |

The hard shell look goes away because layer 2 is now a thin halo (1.1× body) and layer 3 supplies the wispy bulk that BC's SunEffect node draws.

Two empirical constants only — `kCoronaShellRatio = 1.1` and `kFlareOverlayRatio = 1.5`. Both named, both in `sun_pass.cc`.

## Data flow

### `engine/appc/planet.py:aggregate_suns_for_renderer`

```
corona_radius      = radius * 1.1 * scale          # was (radius + atmosphere_thickness) * scale
flare_texture_path = resolve(_flare_texture)       # new field; "" when unset/missing
```

`_flare_texture` is already stashed on the Sun instance by `Sun_Create`. The aggregator resolves it relative to `project_root / "game"` and emits the absolute path. If `_flare_texture` is unset, emit `""`. If it is set but the file is missing on disk, log a once-per-object warning (mirror the existing `_sun_warned` pattern but on a separate `_flare_warned` flag so the body-texture warning and the flare-texture warning fire independently) and emit `""`. The renderer treats `""` as "skip the overlay layer"; the body and corona still draw — different from the missing-`base_texture` path, which drops the sun entirely.

### `renderer::SunDescriptor` — `native/src/renderer/include/renderer/frame.h`

```cpp
struct SunDescriptor {
    glm::vec3   position;
    float       radius        = 1.0f;
    std::string base_texture_path;
    float       corona_radius = 0.0f;        // unchanged semantics: absolute world radius
    std::string flare_texture_path;          // new; empty → skip overlay
};
```

### `engine/renderer.py:set_suns` + `native/src/host/host_bindings.cc:set_suns`

Wire the new `flare_texture_path` dict key through. Existing keys unchanged.

## Renderer changes

### `native/src/renderer/sun_pass.cc`

- Delete `kBodyVisualScale` and `kCoronaVisualScale`. Body draws at `radius * scale_factor`; corona at `corona_radius * scale_factor`.
- After the corona draw, if `flare_texture_path` is non-empty and loads, draw the flare overlay billboard:
  - Camera-facing quad at `virtual_pos`, half-size = `radius * scale_factor * kFlareOverlayRatio`.
  - Additive blend (`SRC_ALPHA`, `ONE`), `GL_DEPTH_TEST` on, depth-write off.
  - Pass `u_now_seconds` so the fragment shader can compute UV rotation. Rotation rate ~5°/s (`0.0873 rad/s`).
- `SunPass::render` gains a `double now_seconds` parameter, mirroring `LensFlarePass::render`. The pipeline calls it with the same time source.

### `native/src/renderer/shaders/sun.frag`

Equator alpha factor `0.6 → 0.54`. Single-character change.

### `native/src/renderer/shaders/sun_flare.{vert,frag}` (new)

Separate pair because the geometry is a billboard quad rather than a sphere and the blend setup differs — clearer than overloading `sun.frag` with another mode flag.

- Vertex: standard camera-aligned billboard. Takes `u_world_center`, `u_half_size`, `u_view`, `u_proj`; emits screen-space corners and `v_uv ∈ [0,1]²`.
- Fragment: samples `u_texture` at UV rotated around `(0.5, 0.5)` by `u_now_seconds * 0.0873`. Output alpha modulated by texture alpha; RGB pre-multiplied for additive.

### `native/src/renderer/pipeline.{cc,h}`

Add `sun_flare_shader()` accessor to mirror the existing `sun_shader()` / `lens_flare_shader()` pattern.

## Tests

### `tests/unit/test_host_loop_suns.py`

Extend `_test_agg_suns_astro_scale` (or add a new case) to assert:

- `corona_radius == pytest.approx(radius * 1.1 * scale)`
- `flare_texture_path` is the absolute path of `_flare_texture` resolved against `project_root / "game"`, when the file exists.
- `flare_texture_path == ""` when no `flare_texture` was passed to `Sun_Create`.
- `flare_texture_path == ""` when `_flare_texture` is set but the file is missing on disk (mirrors the existing missing-base-texture skip-with-warning path).

### `native/tests/renderer/sun_pass_test.cc`

Add cases:

- Descriptor with `flare_texture_path` set + file missing → no GL error, no overlay drawn.
- Descriptor with `flare_texture_path` set + valid TGA fixture → no GL error.
- Existing `CoronaSkippedWhenCoronaRadiusEqualsRadius` / `CoronaDrawnWhenCoronaRadiusGreaterThanRadius` still pass after constants are removed.

## Build / verification

Standard `cmake --build build -j && ./build/dauntless`. After implementation, verify visually in a system that uses every flare texture variant we ship: Biranu (no flare_texture authored), Tevron (Yellow), Cebalrai (Red), Artrus (BlueWhite). The Biranu case is the test that the empty-flare-path code path is harmless.

## Risk register

- **The 1.1× / 1.5× constants are guesses.** They're named and isolated in `sun_pass.cc`; expected to be tuned by eye after first render. If either reads wrong, the fix is a one-line edit.
- **Rotation rate may read wrong** (too fast looks gimmicky; too slow looks static). 5°/s is a starting point; tune in the same pass as the size constants.
- **Lens flare unchanged.** If the at-source `rays` halo now looks too small relative to the new layered sun, that's a known follow-up — not in scope here.
- **Existing missions tuned to the 2× body fudge.** Removing `kBodyVisualScale` means every authored sun reads ~half the angular size it did. This is the *intended* correction (BC's body sphere is real-radius), but means screenshots in mission docs will become stale.
