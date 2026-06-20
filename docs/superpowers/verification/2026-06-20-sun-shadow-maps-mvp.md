# Sun Shadow Maps (MVP) — Visual Verification Recipe

**Branch:** `feat/sun-shadow-maps`
**For:** Mark (live-GUI verification — the renderer/acne tuning steps require running the game and looking at the screen, which the agent does not drive on your workstation).

All code is implemented and the automated suites are green (C++: only the 7 pre-existing `FrameTest.Scorch*`/`PhaserHeatGlow*` readback failures remain; Python: shadow toggle + config-panel tests pass). What remains is visual confirmation and, if needed, one round of acne/cull-face tuning against a pitched hull.

## How to run

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

Load an exterior-view mission with **≥2 ships** (dev pause menu → "Load Mission…"). Dynamic Shadows is **ON by default** (config panel → Modern VFX → "Dynamic Shadows").

## What to confirm

1. **Ship-on-ship cast shadows** — one ship casts a shadow onto another when positioned between it and the sun.
2. **Self-shadowing** — hull greebles/superstructure cast shadows onto the same hull.
3. **Toggle OFF = stock BC** — flip Dynamic Shadows off; the scene must look exactly like before this feature (no shadows, byte-identical lighting). Toggle back on.
4. **Viewscreen** — shadows also appear on ships seen through the bridge viewscreen (the shadow map is computed once per frame and shared across views — confirm it reaches the viewscreen RTT).

## The acne / cull-face tuning checkpoint (the det = −1 basis)

Orient the player ship at a **pitch/roll where the sun rakes across the hull**, then look closely:

- **Shadow acne** (stippled self-shadow speckle on *lit* surfaces) → the depth-pass cull face is wrong for the left-handed (det = −1) basis. Flip it in [native/src/renderer/frame.cc](native/src/renderer/frame.cc) `submit_shadow_depth`: `glCullFace(GL_FRONT)` ↔ `GL_BACK`. Reconfigure not needed (C++ only): `cmake --build build -j`.
- **Peter-panning** (shadows detached from contact points, "floating") → reduce the normal-offset multiplier in [native/src/renderer/shaders/opaque.frag](native/src/renderer/shaders/opaque.frag) (`u_shadow_texel * 1.5` → smaller) and/or lower `glPolygonOffset(2.0f, 4.0f)` in `submit_shadow_depth`. **Shader edit → must `cmake -B build -S .` reconfigure first.**
- Iterate cull-face + bias until a raked hull is clean with grounded contact shadows. Record the chosen values in a code comment citing the det = −1 constraint.

## Two known items to eyeball (carried from review)

- **Player-centering proxy (from Task 5):** there is no C++ player-ship handle (the camera is Python-driven), so the shadow box centers on the **nearest hull to `g_camera.target`**. In a normal chase/orbit exterior view that *is* the player. **Watch for:** if the tracking camera is locked onto an *enemy*, the shadow box may center on that enemy and the player ship could lose its shadow when far from it. If that looks wrong, the clean fix is to plumb the real player world-position + bound-radius from Python (host_loop knows the player) into the shadow system via a new binding — a small follow-up, deliberately deferred from the MVP.
- **Rim-light interaction (from Task 6):** shadowed hull edges no longer pick up the Fresnel rim glow from the (blocked) sun, because the rim term reuses the shadowed sun diffuse. This is physically plausible; confirm it reads well rather than looking like a bug.

## Tuning knobs reference

| Knob | Location | Current value |
|---|---|---|
| Shadow map resolution | `host_bindings.cc` `g_shadow_target->resize(...)` | 2048² |
| Box radius scale `k` / clamp | `ShadowFitParams` defaults in `renderer/shadow_light.h` | `k=3`, clamp `[2,40]` GU |
| Near-extend toward sun / receiver slab | `ShadowFitParams` | `caster_reach=30`, `receiver_depth=30` GU |
| Depth-pass cull face | `frame.cc` `submit_shadow_depth` | `GL_FRONT` (starting guess) |
| Slope/constant bias | `frame.cc` `submit_shadow_depth` | `glPolygonOffset(2.0, 4.0)` |
| Normal-offset bias | `opaque.frag` `sun_shadow_factor` | `u_shadow_texel * 1.5` |
| PCF kernel | `opaque.frag` | 3×3 (9 hardware-compare taps) |

Once it looks right (and any tuning is committed), the branch is ready to merge.
