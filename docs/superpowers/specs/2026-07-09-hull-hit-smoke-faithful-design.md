# Hull-hit smoke — remove non-faithful subsystem plumes, add SDK-faithful impact smoke

**Status:** drafted, awaiting user review
**Date:** 2026-07-09
**Author:** Mark Ward (with Claude)

## 1. Problem

Damaged ships render a giant, persistent white smoke cloud from the ship's
**centre** — most visible at the start of E6M2, where the player's ship (damaged
by mission design) spawns already smoking. The stock game renders that same ship
**clean-hulled**: no plume. So we diverge from BC.

Root cause: the [`engine/appc/subsystem_emitters.py`](../../../engine/appc/subsystem_emitters.py)
plume state machine. Every tick it checks each ship's **master/aggregator**
engine/power subsystems (`WarpEngineSubsystem`, `ImpulseEngineSubsystem`,
`PowerSubsystem`→"warp_core") and, when one reads `IsDamaged/IsDisabled/IsDestroyed`,
spawns a **sustained** smoke plume (`SetEffectLifeTime(1.0e9)`) anchored at
`subsystem.GetPosition()`. For those master subsystems that anchor is the ship
origin or a small belly offset (e.g. Sovereign `WarpEngines` at `(0,0,0)`,
`WarpCore` at `(0,-0.4,-0.2)`), and the DISABLED tier uses the largest particle
size (`fSize` 1.2–1.4, peaking at `2.0×fSize` ≈ 2.8 GU). The result is a
ship-swallowing cloud at centre that never stops.

This whole system is a **Dauntless addition**, not stock behaviour — the spec that
introduced it ([`2026-06-11-subsystem-damage-emitters-design.md`](./2026-06-11-subsystem-damage-emitters-design.md))
calls it the "BC *modded* nacelle plume effect", i.e. modeled on a community mod.

## 2. What stock BC actually does (audit)

Two independent SDK audits (see `sdk/Build/scripts/Effects.py`) confirm: **stock
BC has no continuous, subsystem-state-driven exterior smoke.** Exterior smoke is:

- **Weapon hull-hit puffs** — the real "hull-impact smoke". Handlers in
  `Effects.py`:
  - `TorpedoHullHit` (torpedo reaches hull): always explosion+sound; then **if
    graphics detail ≥ MEDIUM**, 50% sparks and **20% smoke** (`rand(10) < 2`).
  - `PhaserHullHit`: 50% chance to do nothing; otherwise similar, **30% smoke**
    (`rand(10) < 3`).
  - `CreateWeaponSmoke(fDuration, fSize, pEvent, pEffectRoot)` (Effects.py:376) →
    `CreateSmokeHigh(0.2, 2.0 + rand(30)/10, fSize, pEmitFrom, kEmitPos, kEmitDir, pEffectRoot)`
    where `kEmitPos = pEvent.GetObjectHitPoint()` and
    `kEmitDir = pEvent.GetObjectHitNormal()`. Callers pass `fSize = 0.3`.
- **Death / debris explosions** — bursts at `GetRandomPointOnModel()`, only while
  a ship is being destroyed.
- **Interior bridge smoke** — the only *sustained* condition-driven smoke, keyed to
  overall **hull %** on the bridge model (`Bridge/bridgeeffects.py:DoHullDamage`),
  not to any subsystem. Out of scope here.

So stock smoke is: **event-driven by a hull hit**, **at the impact point**, along
the surface normal, **small** (`fSize 0.3`), **transient** (`CreateSmokeHigh` emits
~10s then fades), **probabilistic**, and **detail-gated**. Never continuous, never
subsystem-state-driven, never at ship centre. Corroborating facts: all 16 authored
ship emitters are `ObjectEmitterProperty` (shuttle/probe/decoy launchers) — zero
smoke emitters; `SmokeEmitterProperty` is used only on bridge interiors; no
subsystem class exposes any attach-effect/smoke method.

A ship that is damaged **but not currently taking fire** (E6M2 spawn) therefore
shows a clean hull in stock — exactly the reference screenshot.

## 3. What we already have (reused, not built)

- **Hull-hit dispatch.** [`engine/appc/hit_feedback.py:dispatch`](../../../engine/appc/hit_feedback.py)
  is our reimplementation of the SDK weapon-hit handlers. Its HULL/CRITICAL branch
  already fires spark VFX (`hit_vfx.spawn`) at the impact point and already holds
  everything the smoke needs: `ship`, world `point`, `normal`, `weapon_type`, and
  `ship_instances`. Shield hits take the other branch, so this branch **is** the
  "hull penetration" gate. This is where stock's `TorpedoHullHit`/`PhaserHullHit`
  smoke belongs.
- **SDK particle backend.** [`engine/appc/particles.py`](../../../engine/appc/particles.py)
  reimplements the SDK particle controllers and the `Effects` factories
  (`CreateSmokeHigh`, etc.), with a module-level `_active` registry ticked by
  `advance(dt)` (host_loop:558) and drained each frame by `snapshot_descriptors()`
  → `host_io.set_particle_emitters` → `particle_pass.cc`. `EffectController_GetEffectLevel()`
  (returns `HIGH`) is already present for the detail gate. This pipeline is
  independent of `subsystem_emitters` and is exactly what the faithful smoke reuses.
- **Detail level.** `particles.EffectController` mirrors `App.EffectController`
  (`LOW/MEDIUM/HIGH`); `GetEffectLevel()` returns `HIGH`, so the stock
  `>= MEDIUM` gate passes today but is honoured faithfully.

## 4. Design

### 4.1 Part A — Remove the non-faithful plume system

- **Delete** `engine/appc/subsystem_emitters.py`.
- **Unwire from `engine/host_loop.py`:** the `subsystem_emitters` import; the
  per-tick `subsystem_emitters.pump(ships_list, None, dt)` call (~567); the
  `_se_for_backend.set_backend(ParticleBackend())` install (~1883–1884); the
  `subsystem_emitters.reset_manager()` reset (~3579).
- **Delete `ParticleBackend`** and its `_ControllerHandle` from `particles.py`.
  `ParticleBackend` is the Spec-B adapter that existed **only** to drive the
  plumes — it is what forced `SetEffectLifeTime(1.0e9)` — and it imports
  `subsystem_emitters`. Confirm during implementation it has no other caller
  (expected callers: host_loop `set_backend`, `test_particle_backend`). **Keep**
  the SDK controller classes, the `Effects` factory reimplementations, `_active`,
  `advance`, `snapshot_descriptors`, `register`/`unregister`, `reset`,
  `EffectController*` — all reusable and consumed by other paths (death effects,
  collision avoidance) and by Part B.
- **Tests:** delete the plume-only tests — `test_subsystem_emitters_registry`,
  `_persistence`, `_backend`, `_budget`, `_tiering`, and `test_particle_backend`
  (backend adapter is gone). Adjust any stray `subsystem_emitters` import in
  `test_torpedo_advance` / `test_particle_backend` fixtures. Preserve
  `test_particles_*` that cover the retained SDK controllers/factories.

### 4.2 Part B — SDK-faithful hull-hit smoke

New module `engine/appc/hull_hit_smoke.py`, one public function:

```
maybe_emit(ship, point, normal, weapon_type, ship_instances=None) -> None
```

Behaviour (reproducing `TorpedoHullHit`/`PhaserHullHit` smoke exactly):

1. **Detail gate.** Return unless
   `particles.EffectController_GetEffectLevel() >= particles.EffectController.MEDIUM`.
2. **Probability by weapon** (stock rolls, via `App.g_kSystemWrapper.GetRandomNumber`
   to match SDK RNG semantics):
   - `"torpedo"` → emit iff `GetRandomNumber(10) < 2` (20%).
   - `"phaser"` → emit iff `GetRandomNumber(10) < 3` (30%).
   - anything else / `None` → no smoke (stock only wires torpedo + phaser hull hits).
3. **Emit** the SDK recipe (equivalent to `CreateWeaponSmoke` → `CreateSmokeHigh`):
   `CreateSmokeHigh(fVelocity=0.2, fLife=2.0 + GetRandomNumber(30)/10.0, fSize=0.3,
   pEmitFrom=ship, kEmitPos=point, kEmitDir=normal, pAttachTo=ship)`. Invoke through
   the retained `Effects`/particle path so the controller registers in
   `particles._active`, ticks under `advance()`, renders via `particle_pass`, and
   self-expires (~10s) — no lifetime override. `emit_from=ship` lets
   `_build_particle_render_data`'s `_resolve_emit_attach` glue the puff to the moving
   hull; `kEmitPos`/`kEmitDir` are the world hit point + surface normal.

The constants (`0.2`, `0.3`, `2.0 + rand(30)/10`, the 20%/30% rolls, the `>= MEDIUM`
gate) are copied verbatim from `Effects.py`; none are re-tuned.

### 4.3 Hook

In `hit_feedback.dispatch`, HULL/CRITICAL branch (the `else` after the SHIELD
branch, alongside the existing `hit_vfx.spawn`), call:

```
hull_hit_smoke.maybe_emit(ship, point, normal, weapon_type, ship_instances)
```

`normal` may be `None` (mesh trace missed / sphere-entry fallback). Stock always
has a hit normal from the event; our fallback **skips** the puff when `normal is
None` rather than emit a mis-directed one. Import `hull_hit_smoke` lazily inside
`dispatch` (same deferred-import pattern already used there for
`hit_vfx`/`camera_shake`) to avoid import cycles.

### 4.4 Boundaries / isolation

- `hull_hit_smoke` depends only on `particles` (factory + detail level) and the
  `App` RNG. It does **not** know about `hit_feedback`, combat, or the renderer.
  Testable in isolation by mocking the RNG, the detail level, and the factory.
- `hit_feedback.dispatch` gains exactly one call; no signature change (it already
  receives `weapon_type`, `point`, `normal`, `ship_instances`).
- No native/C++ change. The particle render pass and host bindings are untouched.

## 5. Testing

- **Unit — `hull_hit_smoke`:**
  - torpedo/phaser probability gating with mocked `GetRandomNumber` (fires at
    `<2`/`<3`, silent at/above);
  - detail-level gate (no emit below MEDIUM);
  - emit position == hit point and direction == normal (assert the factory call
    args);
  - `weapon_type` None / unknown → no emit;
  - `normal is None` → skip (no emit).
- **Faithfulness:** a test asserting the stock `CreateSmokeHigh` constants for the
  hull-hit smoke, mirroring `test_particles_sdk_unmodified`.
- **Integration:** `hit_feedback.dispatch` on a HULL hit routes to `maybe_emit`
  (mock it, assert called with the hit point); a SHIELD hit does not.
- **Removal:** deleting `subsystem_emitters` leaves `particles`/`particle_pass`
  green; `scripts/check_tests.sh` gate passes with no new failures beyond the
  known-failures ledger.
- **Verify (`/verify`):** load E6M2 → spawn renders **clean** (no centre cloud);
  take hull fire in QuickBattle → transient smoke puffs appear **at impact points**,
  fading after a few seconds. Ramming still produces its (separately-correct) hull
  breach VFX.

## 6. Out of scope

- Interior bridge hull-% smoke (`bridgeeffects.DoHullDamage`) — separate SDK path,
  unaffected.
- Hull-breach venting / carve VFX (`breach_venting.cc`, `visible_damage.py`) —
  correct and untouched.
- The E6M2 player spawning damaged — **expected mission design**; with the plume
  removed it correctly renders clean until hit.

## 7. File-change summary

| File | Change |
|---|---|
| `engine/appc/subsystem_emitters.py` | **delete** |
| `engine/appc/particles.py` | remove `ParticleBackend` + `_ControllerHandle`; keep controllers/factories/registry |
| `engine/host_loop.py` | drop import, `pump()`, `set_backend()`, `reset_manager()` |
| `engine/appc/hull_hit_smoke.py` | **new** — `maybe_emit(...)` |
| `engine/appc/hit_feedback.py` | one call in HULL/CRITICAL branch |
| `tests/unit/test_subsystem_emitters_*.py` (×5) | **delete** |
| `tests/unit/test_particle_backend.py` | **delete** (adapter gone) |
| `tests/unit/test_torpedo_advance.py` | drop stray `subsystem_emitters` import if present |
| `tests/unit/test_hull_hit_smoke.py` | **new** |
