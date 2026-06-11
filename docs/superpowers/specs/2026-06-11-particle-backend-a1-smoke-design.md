# Particle Backend A1 — render primitive + smoke controller (Spec A, slice 1)

**Status:** drafted, awaiting user review
**Date:** 2026-06-11
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-11-subsystem-damage-emitters-design.md`](./2026-06-11-subsystem-damage-emitters-design.md) — **Spec B**, the subsystem-plume state machine. Its §5 defines the backend interface this spec implements. Spec B currently runs on `NullBackend`; A1 provides the real backend and flips it live. **Spec B's logic is not touched.**
- `native/src/renderer/hit_vfx_pass.cc` — the existing **stateless procedural** VFX renderer (sparks computed analytically from `age` + `hash3`/`rotate_jitter`, hull-anchored via in-pass `instance_id` world-matrix lookup, billboard quad). A1 mirrors this pattern and reuses its helpers.
- `native/src/renderer/dust_pass.cc` — camera-anchored particle pass; precedent for a continuous particle pass with a `set_*`/global/`render` host wiring.
- `native/src/host/host_bindings.cc` (`set_hit_vfx`, `set_phaser_beams`) — the **Python-pushes-descriptors → C++ global vector → `*Pass::render` each `frame()`** pattern A1 follows.
- SDK `sdk/Build/scripts/Effects.py` — `CreateSmokeHigh` (222), `CreateWeaponSmoke` (376), `CreateDebrisSmoke` (422). **These factory bodies are not rewritten** (see §1).

## 0. Where A1 sits in Spec A

The brainstorm chose the **full Effects.py particle surface** as Spec A's eventual scope, then decomposed it into vertical slices by controller family (each its own spec → plan → implementation cycle):

- **A1 (this spec)** — particle render primitive + `AnimTSParticleController` (smoke) + the smoke factories (`CreateSmokeHigh`, `CreateWeaponSmoke`, `CreateDebrisSmoke`) + the Spec B backend wiring. The load-bearing slice: it builds the renderer pass everything else reuses, and it lights up Spec B's subsystem plumes end-to-end (plumes call `CreateSmokeHigh`).
- **A2 (later)** — `ExplosionPlumeController` + `CreateExplosionPlumeHigh` / `CreateExplosionPuff{High,Med,Low}` / `CreateObjectExplosion` + `TGSequence` composition. Completes Spec B's warp-core and death-puff visuals.
- **A3 (later)** — `SparkParticleController` + `CreateWeaponSparks` / `CreateDebrisSparks`, reconciled with the existing procedural sparks in `hit_vfx_pass`.

## 1. Key architectural decision — SDK `Effects.py` runs unmodified

SDK `Effects.py`'s smoke factories are already written against `App.AnimTSParticleController_Create()` and a fixed controller method set. Today those App-level names fall through `App.__getattr__` into `_NamedStub` (recording the call, doing nothing). **A1 makes those App-level primitives real**, so the SDK factory bodies run **completely unmodified** and produce real particles. A1 does **not** fork or rewrite any `Create*` function.

The exact surface the three smoke factories touch (verified against `Effects.py`):

- `App.AnimTSParticleController_Create()` → a real controller object.
- Controller methods: `AddColorKey(t,r,g,b)`, `AddAlphaKey(t,a)`, `AddSizeKey(t,s)`, `CreateTarget(path)`, `SetEmitFromObject(av)`, `AttachEffect(node)`, `SetEmitVelocity(v)`, `SetEmitLife(l)`, `SetEmitLifeVariance(v)`, `SetEmitFrequency(f)`, `SetEffectLifeTime(t)`, `SetAngleVariance(deg)`, `SetInheritsVelocity(0|1)`, `SetEmitPositionAndDirection(pos,dir)`, `SetDrawOldToNew(0|1)`, `SetDetachEmitObject(0|1)`, `SetTargetAlphaBlendModes(...)`.
- `App.EffectAction_Create(controller)` → an action whose `Start()`/`Stop()` register/deregister the controller in the active registry.

This is the established shim pattern (`engine/appc/properties.py` factories imported into `App.py`): controller classes live in `engine/appc/particles.py`; `App.py` imports the `*_Create` factories.

## 2. Four layers

| Layer | File(s) | Responsibility |
|---|---|---|
| Renderer pass | `native/src/renderer/particle_pass.cc`; `ParticleEmitterDescriptor` in `native/src/renderer/include/renderer/frame.h` | Stateless analytic billboard particle renderer (§3, §4). |
| Host binding | `native/src/host/host_bindings.cc` | `set_particle_emitters(descs)` global vector + `ParticlePass::render(...)` in `frame()`, next to the `hit_vfx` pass. |
| Python controller core | `engine/appc/particles.py` | `AnimTSParticleController` (stores keyframes + emit params + attach target — **no simulation**), the module-level active registry (`advance`, `snapshot_descriptors`, `reset`), `EffectAction_Create`, the `*_Create` factory imported into `App.py`. |
| Spec B backend | `engine/appc/particles.py` (`ParticleBackend`) | Implements Spec B §5 (`create`/`fire_one_shot` → build a controller via the smoke factory, return a handle with `stop_emitting`/`has_live_particles`); wired via `subsystem_emitters.set_backend(...)` at host startup. |

**Per-frame flow.** The host loop, next to the existing `set_hit_vfx` block, calls `particles.advance(dt)` then `_h.set_particle_emitters(particles.snapshot_descriptors())`. C++ stores the list; `ParticlePass::render` draws each emitter analytically. One registry feeds **both** SDK-script-spawned effects and Spec B subsystem plumes — a single path.

## 3. The stateless analytic particle model

The renderer owns all motion; Python never simulates a particle. Each `ParticleEmitterDescriptor` carries:

- `instance_id` (optional ship anchor; `{0,0}` sentinel = unattached),
- `emit_pos_world`, `emit_dir_world`, `emit_vel_world` (ship world velocity), `inherit` ∈ [0,1] (`SetInheritsVelocity`),
- `emit_velocity`, `angle_variance` (deg), `emit_life`, `emit_life_variance`, `emit_frequency`,
- `effect_age`, `stop_age` (= +∞ while emitting),
- `draw_old_to_new` (0|1),
- keyframe curves: `color_keys[(t,r,g,b)]`, `alpha_keys[(t,a)]`, `size_keys[(t,s)]` — small fixed-cap arrays (≤8 keys each),
- `texture_id`.

**Slot-based emission.** Max live particles `N = ceil(max_life / emit_frequency)` where `max_life = emit_life + emit_life_variance`. For slot `i ∈ [0,N)`:
```
period  = N · emit_frequency
b_i     = effect_age − ((effect_age − i·emit_frequency) mod period)   // birth age of the current occupant of slot i
τ       = effect_age − b_i                                            // sub-age
life_i  = emit_life + hash_i · emit_life_variance
cull if (τ > life_i) or (b_i > stop_age) or (b_i < 0)
```

**World position (velocity-inherited trail):**
```
dir_i   = cone_jitter(emit_dir_world, angle_variance, hash_i)         // SDK SetAngleVariance
pos_i   = emit_pos_world + dir_i·emit_velocity·τ − (1 − inherit)·emit_vel_world·τ
```
The `−(1−inherit)·emit_vel_world·τ` term is the trail: `inherit=1` ⇒ particles ride with the ship (no trail); `inherit<1` ⇒ older particles lag aft. Fully analytic from the *current* descriptor — no position history buffer.

**Appearance.** `t = τ / life_i ∈ [0,1]`; `size = curve_lerp(size_keys, t)`, `rgb = curve_lerp(color_keys, t)`, `alpha = curve_lerp(alpha_keys, t)`. `curve_lerp` is piecewise-linear over the `(t,value)` keys — the exact semantics of SDK `AddSizeKey`/`AddColorKey`/`AddAlphaKey` (clamp below the first key and above the last).

**Emit-from-object resolution.** When `instance_id` is set, the pass looks up the ship's live world matrix (the spark path) and transforms the **body-frame** emit point/dir (`SetEmitPositionAndDirection` + `SetEmitFromObject`) into `emit_pos_world`/`emit_dir_world` *that frame*; the host supplies `emit_vel_world` from physics. Unattached ⇒ fixed `emit_pos_world`, `emit_vel_world = 0`.

**`stop_emitting()` / `has_live_particles()`** are analytic: `stop_emitting()` sets `stop_age = effect_age`; `has_live_particles()` is `stop_age + max_life > effect_age`. Fade-on-stop falls out of the indexing math (no new particles past `stop_age`; existing ones finish their `life_i`).

## 4. Renderer pass

`ParticlePass` (`native/src/renderer/particle_pass.cc`), modeled on `hit_vfx_pass`:

- One camera-facing quad mesh; **alpha-blend** pipeline (`SRC_ALPHA, ONE_MINUS_SRC_ALPHA` — smoke, unlike additive sparks); depth-test **on**, depth-write **off** (plumes sort against scene geometry without z-fighting each other).
- `render(emitters, world, camera, pipeline)`: per descriptor, resolve the emit frame (instance-id world-matrix lookup, else fixed world pos), then loop `i = 0…N−1` running the §3 math, evaluating the three keyframe curves, discarding culled particles. `draw_old_to_new` selects sort direction.
- Reuses `hash3`, `rotate_jitter`, the quad, and `load_sprite` from the existing VFX code. If a clean shared helper header is natural, refactor them out; otherwise duplicate minimally. (`hit_vfx_pass` is **not** restructured beyond extracting shared helpers if chosen.)
- `ParticleEmitterDescriptor` lands in `frame.h` beside `HitVfxDescriptor`; keyframe curves upload as small fixed-cap arrays.
- A1 ships the smoke sprites the three factories reference (`data/Textures/Effects/ExplosionB.tga` and any others in those bodies).

## 5. Python controller, registry, factories, backend

**`AnimTSParticleController`** — a plain object accumulating exactly what the SDK setters push (§1), no simulation. Setters store fields; unknown/irrelevant setters are accepted as harmless no-ops so future SDK calls never crash. Getters needed by the renderer are read by `snapshot_descriptors()`.

**Registry** (mirrors `hit_vfx.py`): module-level `_active`. A controller enters `_active` when its `EffectAction.Start()` runs, carrying a birth game-time. `advance(dt)` ages each controller's `effect_age` and prunes when `effect_age > EffectLifeTime` **and** `has_live_particles()` is false. `snapshot_descriptors()` resolves each live controller's emit-from-object handle → `instance_id` + body frame (+ ship velocity from physics) and emits one `ParticleEmitterDescriptor`. `reset()` clears `_active` on mission swap (same hook that calls `subsystem_emitters.reset_manager`).

**`EffectAction_Create(controller)`** returns a small action whose `Start()` registers and `Stop()` deregisters the controller — matching how SDK wraps every effect in an action/sequence.

**Texture handling.** `CreateTarget(path)` maps the SDK texture path to a renderer texture id; the pass lazy-loads via `load_sprite`.

**`ParticleBackend`** (Spec B §5):
- `create(factory, params, emit_pos_body, emit_dir, direction_mode)` → look up the SDK factory by name, call it with `pEmitFrom` = the ship's AV object + the body-frame emit pos/dir, `Start()` the returned `EffectAction`, return a handle wrapping the controller. `handle.stop_emitting()` → controller `stop_age = effect_age`; `handle.has_live_particles()` → the controller's analytic check. `SPHERICAL` ⇒ wide/full-sphere `SetAngleVariance`; `FIXED_BODY_VECTOR`/`ALONG_SUBSYSTEM_AXIS` ⇒ the resolved dir.
- `fire_one_shot(factory, emit_pos_body, emit_dir)` → a controller with a short `EffectLifeTime`, fire-and-forget.

Wired once at host startup: `subsystem_emitters.set_backend(ParticleBackend())`. Spec B's plumes then render for real with **no change to Spec B's code** (it flips from `NullBackend` to live).

## 6. Testing

Mirrors the project split: pure-Python unit tests + offscreen `FrameTest` render tests that `GTEST_SKIP` without BC assets.

**Python — controller/registry:**
1. Each setter round-trips its value; unknown setter is a no-op (no crash).
2. `EffectAction.Start/Stop` register/deregister in `_active`.
3. `advance(dt)` ages `effect_age`; prunes only after `EffectLifeTime` AND `has_live_particles()` false.
4. `snapshot_descriptors` resolves emit-from-object → `instance_id` + body-frame emit pos/dir + ship velocity.
5. `stop_emitting` → `has_live_particles` analytic timeline: true until `stop_age + max_life`, then false.

**Python — Spec B backend:**
6. `create("CreateSmokeHigh", …)` registers a controller and returns a handle whose `stop_emitting`/`has_live_particles` drive that controller.
7. `SPHERICAL` vs `FIXED_BODY_VECTOR` set the expected spread/dir on the controller.
8. `fire_one_shot` registers a short-lived controller.
9. **End-to-end:** `subsystem_emitters.set_backend(ParticleBackend())`, then a disabled nacelle (via `PlumeManager.update`) registers a smoke emitter — Spec B → A1, headless.

**Python — SDK-unmodified proof:**
10. Import SDK `Effects.py`; call `CreateSmokeHigh(...)`, `CreateWeaponSmoke(...)`, `CreateDebrisSmoke(...)` against the real controller; assert a controller with the SDK's exact keyframes/params is registered and **no `_NamedStub` rows** are recorded for the controller methods (stub-tracker regression).

**Renderer — `FrameTest` (llvmpipe, skips without assets):**
11. An emitter at a known frame renders the analytically-expected particle positions.
12. A moving emitter (`emit_vel_world ≠ 0`, `inherit < 1`) places older particles aft of newer (trail); at `inherit = 1` no trail.
13. `stop_age` past `max_life` renders nothing.
14. `glGetError() == GL_NO_ERROR`; a no-emitter frame is byte-identical to the pre-change baseline.

## 7. Parking lot (tune-by-eye)

- Final keyframe curves / sprite choices / `emit_frequency` / velocities per smoke factory (the SDK values are the starting point).
- Soft-particle depth softening (fade where a billboard intersects geometry).
- Max particles per emitter cap and any global particle budget (Spec B's per-ship plume cap already bounds plume emitters; mission-script effects are bounded by `EffectLifeTime`).
- Keyframe array cap (start at ≤8; revisit if a factory needs more).

## 8. Non-goals

- `ExplosionPlumeController` & explosion/puff factories — **A2**.
- `SparkParticleController` & weapon/debris sparks + reconciling the existing `hit_vfx` procedural sparks — **A3**.
- `TGSequence` composition beyond the single-action Start/Stop A1 needs — **A2**.
- Stateful particle pools / per-particle history (explicitly rejected — model is stateless analytic, §3).
- Final art/tuning values, soft particles — parking lot (§7).
- Save/load of particle state — runtime-only, re-spawned by SDK scripts / re-derived by Spec B from predicates (matches every other VFX system).
- Rewriting any SDK `Effects.py` factory body (§1).

## 9. Workflow

This spec → one implementation plan (writing-plans) → `docs/superpowers/plans/`, executed via subagent-driven-development. Suggested ordering inside the plan: renderer pass + descriptor (with a hand-built descriptor render test) → Python controller + registry + `EffectAction` → host-loop wiring + `snapshot_descriptors` → SDK-unmodified factory proof → `ParticleBackend` + `set_backend` wiring + the Spec B end-to-end test. Merging A1 makes Spec B's subsystem plumes visible in-game.
