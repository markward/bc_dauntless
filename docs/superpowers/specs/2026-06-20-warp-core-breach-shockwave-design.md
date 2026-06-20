# Warp-Core Breach Shockwave — Design

**Date:** 2026-06-20
**Status:** Approved, pending implementation plan
**Area:** Phase 2 renderer / warp-core breach VFX

## Summary

Replace the warp-core breach's current "fluffy" `ExplosionA` puff fireball
(`warp_core_breach._spawn_fireball`) with a **procedural blue-white shockwave**:
a fast-expanding flat **ring** thrown out from the warp core plus a brief
**white-hot core flash**. The ring is **camera-facing** (always seen as a full
circle, never edge-on) and expands **well beyond** the gameplay blast radius for
a dramatic read. No new art assets — everything is generated in a GLSL pass
modeled on the existing camera-anchored `dust_pass`.

## Motivation

The breach is the climactic event of a ship's destruction, but its VFX is a few
slow `ExplosionA` sprite puffs that read as soft smoke, not a violent
matter/antimatter detonation. A bright flash + expanding ring gives the breach
the explosive, cinematic punch it deserves. (The companion "selectable wreck
linger" change already lets the player catch the wreck and watch this play.)

## Decisions (locked during brainstorming)

| Aspect | Decision |
|---|---|
| Silhouette | Flat **ring** + bright **core flash** |
| Puffs | **Replaced** — `_spawn_fireball` removed; no debris/smoke |
| Orientation | **Camera-facing** billboard (rotationally symmetric ring → no spin artifact, never edge-on) |
| Color | **White-hot** core flash → cold **blue-white** ring (warp-core energy) |
| Ring size | **Bigger / dramatic** — fixed `SHOCKWAVE_MAX_RADIUS_GU = 4.0` (well past the 1.3 GU blast radius), tunable |
| Lifetime | `SHOCKWAVE_LIFETIME = 0.7 s` (tunable) |

## Architecture

Two halves, each mirroring an existing pattern.

### Python (registry + spawn) — `engine/appc/shockwaves.py` (new)

Modeled on `engine/appc/hit_vfx.py` (transient, age-driven world VFX):

- `spawn(center_world, max_radius_gu, lifetime)` — append a descriptor
  `{center, max_radius, age: 0.0, lifetime}`.
- `advance(dt)` — age every descriptor; drop those with `age >= lifetime`.
- `render_data()` — return a list of
  `(center_xyz, max_radius, age, lifetime)` tuples for the host.
- `reset()` — clear the registry (mission swap / test teardown).

`warp_core_breach.detonate` replaces its `_spawn_fireball(ship, core)` call with
`shockwaves.spawn(centre, SHOCKWAVE_MAX_RADIUS_GU, SHOCKWAVE_LIFETIME)` (still
raise-safe). `centre` is the warp core world position already computed in
`detonate`. The old `_spawn_fireball` and its `Effects`/`ExplosionA` use are
deleted.

`engine/host_loop.py`:
- In the per-frame combat hub, advance the registry beside
  `hit_vfx.update_ages(dt)`: `shockwaves.advance(dt)`.
- In the frame build (where `host.set_torpedoes(...)` is pushed), push the
  render data: `host.set_shockwaves(shockwaves.render_data())` — guarded with
  `hasattr(host, "set_shockwaves")` so the headless/no-renderer path is a no-op.
- Add `shockwaves.reset()` beside the existing `ship_death.reset()` /
  `warp_core_breach.reset()` in the mission-swap reset block.

### Native (rendering) — `native/src/renderer/shockwave_pass.{h,cc}` (new)

Modeled on `native/src/renderer/dust_pass.{h,cc}`:

- **Descriptor** (`native/src/renderer/include/renderer/frame.h`):
  `struct ShockwaveDescriptor { glm::vec3 world_center; float max_radius;
  float age; float lifetime; };` — same age/lifetime shape as
  `TorpedoDescriptor` / `HitVfxDescriptor`.
- **Pass** (`ShockwavePass`): a single camera-facing billboard **quad** per
  shockwave, expanded to the current ring radius in the vertex shader using the
  camera right/up basis (the `subsystem_pin_pass` / `dust_pass` billboard math).
  Additive blending (`GL_SRC_ALPHA, GL_ONE`), depth-test `LEQUAL`, depth-write
  off, cull off — the `dust_pass` setup, so nearer hulls occlude the ring but it
  never fights itself. `render(cam, shockwaves, pipeline)` iterates the
  descriptors.
- **Shaders** (`native/src/renderer/shaders/shockwave.vert` + `.frag`, embedded
  via `embed_shader` in `native/src/renderer/CMakeLists.txt`, accessor on
  `Pipeline`): the fragment shader, given the quad's radial coordinate `r∈[0,1]`
  and a normalized age `t = age / lifetime`, renders **both**:
  - **Ring:** a thin bright annulus band centered at the current expansion
    fraction; radius grows with an **ease-out** curve (bursts fast, decelerates)
    from ~0 to `max_radius`; alpha fades as `t→1`. Color cools from white-hot to
    blue-white as it grows.
  - **Core flash:** a bright central additive glow, strong only for the first
    ~20 % of life (`t < 0.2`), then gone. Folded into the same shader — one
    quad, one draw.
- **Host wiring** (`native/src/host/host_bindings.cc`): a global
  `std::vector<renderer::ShockwaveDescriptor> g_shockwaves;` and
  `std::unique_ptr<renderer::ShockwavePass> g_shockwave_pass;`, constructed in
  `init()` / destroyed in `shutdown()` like `g_dust_pass`. A `set_shockwaves`
  pybind binding (the `set_torpedoes` pattern) replaces `g_shockwaves`. In
  `frame()`, in the additive-VFX band (after hit-VFX / particle emitters, before
  hologram/pins), call `g_shockwave_pass->render(cam, g_shockwaves, *g_pipeline)`
  — **main view only** (`if (!for_viewscreen)`, matching dust).

## Data flow

```
warp_core_breach.detonate(ship)
  centre = warp core world position
  shockwaves.spawn(centre, SHOCKWAVE_MAX_RADIUS_GU, SHOCKWAVE_LIFETIME)
        │
        ▼  (each tick, host_loop combat hub)
shockwaves.advance(dt)                 # age, drop expired
host.set_shockwaves(shockwaves.render_data())   # push [(center, max_r, age, life), ...]
        │
        ▼  (native frame())
g_shockwave_pass->render(cam, g_shockwaves, pipeline)
   per descriptor: billboard quad sized to easeOut(t)*max_radius,
   frag draws annulus ring + (t<0.2) core flash, blue-white, additive
```

## Tunables (shader/Python constants, by feel)

| Constant | Default | Meaning |
|---|---|---|
| `shockwaves.SHOCKWAVE_MAX_RADIUS_GU` | 4.0 | Ring max radius (well past the 1.3 GU blast) |
| `shockwaves.SHOCKWAVE_LIFETIME` | 0.7 s | Total ring/flash lifetime |
| ring band width, ease-out exponent, flash duration fraction, colors | shader-side | Visual feel |

## Error handling

- `shockwaves.spawn` is called from the raise-safe section of `detonate`; a
  failure cannot block the AoE damage path.
- `host.set_shockwaves` is `hasattr`-guarded — headless/no-renderer runs no-op.
- The pass is purely additive and never writes depth, so a shader/asset failure
  degrades to "no ring," never corrupts the scene.

## Testing

- **Python unit tests** (real coverage, headless): `shockwaves.spawn` / `advance`
  (age increments; descriptor dropped at `age >= lifetime`) / `render_data`
  (tuple shape and values) / `reset`; and that `warp_core_breach.detonate`
  spawns exactly one shockwave at the core center (spy on `shockwaves.spawn`)
  and no longer calls the removed `_spawn_fireball`.
- **Native:** no GL unit test (consistent with `dust_pass` and the other
  passes). Verified visually in-app by the user. The plan ensures the pass
  compiles, the shaders embed, and `frame()` renders without GL error.

## Build / rebuild notes

- New shader files + new source require a **cmake reconfigure**
  (`cmake -B build -S .`), not just `cmake --build` — shader embedding and the
  new translation unit are picked up at configure time.
- `host_bindings.cc` changes require rebuilding the `dauntless` target (the
  module is compiled into both the binary and `_dauntless_host`).

## Non-goals

- No spherical shell, twin rings, or debris/smoke (silhouette is ring + flash).
- No allegiance/size-scaled ring (fixed `SHOCKWAVE_MAX_RADIUS_GU`).
- No render-to-texture / viewscreen rendering of the shockwave (main view only).
- No change to breach gameplay (damage, radius, chains) — purely visual.

## Affected files

| File | Change |
|---|---|
| `engine/appc/shockwaves.py` | New — Python registry (spawn/advance/render_data/reset) |
| `engine/appc/warp_core_breach.py` | Replace `_spawn_fireball` with `shockwaves.spawn` |
| `engine/host_loop.py` | Advance + `set_shockwaves` push + reset wiring |
| `native/src/renderer/include/renderer/frame.h` | `ShockwaveDescriptor` |
| `native/src/renderer/shockwave_pass.{h,cc}` | New — GL pass |
| `native/src/renderer/shaders/shockwave.{vert,frag}` | New — ring + flash shader |
| `native/src/renderer/CMakeLists.txt` | `embed_shader` for the new shaders |
| `native/src/renderer/include/renderer/pipeline.h`, `pipeline.cc` | Shader accessor |
| `native/src/host/host_bindings.cc` | Global, init/shutdown, `set_shockwaves` binding, `frame()` render call |
| `tests/unit/test_shockwaves.py` | New — registry tests |
| `tests/unit/test_warp_core_breach.py` | Update — detonate spawns shockwave, not fireball |
