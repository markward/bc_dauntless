# Filmic Ambient Dimming — Design

**Date:** 2026-06-21
**Status:** Approved, implementing
**Extends:** [Filmic Filter](2026-06-21-filmic-filter-design.md)

## Summary

When the Filmic Filter toggle is **on**, reduce the **main exterior view's**
ambient light term to **0.64** (≈−36%, the original −20% applied twice: 0.8×0.8;
multiply `lighting.ambient` by `0.64`). Off →
full ambient. Scope matches the filmic post-effect exactly: bridge interior and
the bridge viewscreen inset keep full ambient at all times.

## Why a scene-render hook (not the filmic shader)

Ambient is applied in the 3D opaque pass (`opaque.frag`'s `u_ambient_light`),
which runs *before* post-processing. The filmic post pass runs at the end of the
pipeline and cannot affect scene lighting, so the dimming must be applied where
ambient is bound at scene-render time.

## Mechanism

1. **Helper (testable seam):** add to the `dauntless_filmic` namespace in
   `frame.cc`:
   ```cpp
   constexpr float kFilmicAmbientScale = 0.64f;  // ~-36% ambient when filmic on (0.8x0.8)
   float ambient_scale() { return g_filmic_enabled ? kFilmicAmbientScale : 1.0f; }
   ```

2. **Submit path:** `FrameSubmitter::submit_opaque_in_pass` (the function
   `render_space` uses) gains a trailing `float ambient_scale = 1.0f` parameter.
   Its `configure_common` sets
   `u_ambient_light = lighting.ambient * ambient_scale`. The default `1.0f`
   keeps every other caller byte-identical.

3. **Host wiring:** in `host_bindings.cc`'s `render_space` lambda, pass
   `(!for_viewscreen) ? dauntless_filmic::ambient_scale() : 1.0f`. The exterior
   render only runs when `!bridge_active`, and the viewscreen path passes
   `for_viewscreen=true`, so the dimming is naturally restricted to the main
   exterior view.

## Scope / behavior table

| View | Filmic ON | Filmic OFF |
|---|---|---|
| Main exterior | ambient ×0.64 + grain/vignette/CA | ambient ×1.0, no filter |
| Viewscreen inset | ambient ×1.0, no filter | ambient ×1.0, no filter |
| Bridge interior | ambient ×1.0 (separate lighting) | ambient ×1.0 |

Unlike the global bloom tweak, this is gated by the filmic toggle and
exterior-only: turning Filmic off fully restores the original lighting.

## Testing

- Unit-test `dauntless_filmic::ambient_scale()`: `0.64` when enabled, `1.0` when
  disabled (no GL; mirrors the existing `DauntlessFilmicToggle` test).
- Wiring (host passes scale, shader multiplies) verified by clean build + live
  check, consistent with how the host routing was verified in the filmic plan
  Task 3.

## Decisions captured

- Ambient dim = multiply by `0.64` (≈−36%; live-tuned from the initial 0.8), named `kFilmicAmbientScale`.
- Exterior-only, gated by the filmic toggle.
- Default-`1.0f` param keeps all non-exterior render paths untouched.
