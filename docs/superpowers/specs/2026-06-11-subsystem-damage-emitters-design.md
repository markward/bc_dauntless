# Subsystem Damage Emitters — sustained state-driven plumes (Spec B)

**Status:** drafted, awaiting user review
**Date:** 2026-06-11
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-09-impact-feedback-design.md`](./2026-06-09-impact-feedback-design.md) — transient one-shot hit feedback. Its §7 explicitly defers *"sustained, state-driven subsystem emitters (nacelle venting, etc.)"* to this work. **This spec is that deferred system.**
- [`2026-06-08-persistent-damage-decals-design.md`](./2026-06-08-persistent-damage-decals-design.md) — persistent body-space scorch. The decal record list is impact-keyed; **it does not drive these emitters.** Plumes key off subsystem *state predicates*, not impact records.
- [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) and the damage-attribution work — `engine/appc/combat.py:apply_hit` allocates damage to subsystems and `engine/appc/subsystems.py` exposes `IsDamaged()` / `IsDisabled()` / `IsDestroyed()` on every subsystem. **Consumed, not redesigned.**
- [`2026-05-12-object-emitter-emission-design.md`](./2026-05-12-object-emitter-emission-design.md) — the `ObjectEmitterProperty` / `LaunchObject` machinery for shuttles/probes/decoys. **Unrelated** — that is object launching, not particle emission.
- SDK `sdk/Build/scripts/Effects.py` — `CreateSmokeHigh` (222), `CreateExplosionPlumeHigh` (179), `CreateDebrisSmoke` (422), `CreateWeaponSparks` (329). These factory names and their controller recipes are the interface this system builds on.

## 0. The two-spec split (read first)

The original BC "modded nacelle plume" effect is built from SDK particle controllers
(`AnimTSParticleController_Create`, `ExplosionPlumeController_Create`,
`SparkParticleController_Create`) assembled by the `Effects.py` factories. **None of
those controllers exist as real, renderer-backed implementations in our engine today** —
the `_Create` names fall through `App.__getattr__` into `_NamedStub`, recording the call
and doing nothing. The only real particle path today is `engine/appc/hit_vfx.py` →
`native/src/renderer/hit_vfx_pass.cc` (and `dust_pass.cc`).

The work is therefore split into two sequenced specs:

- **Spec A (separate, later brainstorm) — particle-controller backend.** Real,
  renderer-backed implementations of the SDK particle controllers behind the `Effects.py`
  factory names. Owns particles: color/alpha/size keys, emit life/frequency, angle
  variance, emit-from-object world resolution, inherit-velocity, detach.
- **Spec B (this document) — the subsystem-plume state machine.** Owns *policy*: which
  subsystem state triggers which plume, where it anchors, when it starts/stops/fades, the
  severity ladder, the per-ship budget, and the mod registration table. It **consumes**
  Spec A through the `Effects.py` factory interface (§5).

Spec B can be **built and unit-tested immediately** against a `FakeControllerBackend` test
double (§5, §6). Visual bring-up waits on Spec A landing. Implementation sequencing: Spec A
first, then Spec B's visual pass; Spec B's logic has no runtime dependency on Spec A's
internals, only its interface.

## 1. Goal

A sustained, **state-driven** 3D particle effect anchored to damaged-subsystem hardpoints:
damaged warp nacelles vent plasma, damaged impulse engines smoke, the damaged warp core
sparks/arcs. The effect emits *continuously while a subsystem-state predicate holds* and
fades when the predicate clears (repair). This is distinct from:

- **one-shot impact effects** (sparks, torpedo flicker) — shipped, event-driven, `hit_vfx`;
- **persistent scorch decals** — shipped, impact-record-driven, body-space composited.

Plumes are **predicate-driven**: they exist because a subsystem *is* in a damage state, not
because a hit *happened*.

## 2. What is already in place (consumed, not built)

- **Subsystem state predicates.** `IsDamaged()` / `IsDisabled()` / `IsDestroyed()` on every
  subsystem instance (`engine/appc/subsystems.py`). Parent-aggregator predicates propagate
  child state upward — **this system ignores aggregators** and keys only off *leaf*
  subsystems that own a real hardpoint (§3).
- **Hardpoint anchor.** `subsystem.GetPosition()` returns the body-frame hardpoint offset
  (the world-*scale* body offset; no model scale — per CLAUDE.md's hardpoint-position-frame
  note and `engine/appc/combat.py:_subsystem_world_position`). Body→world is
  `v_world = ship_pos + R · v_body` under the column-vector convention.
- **Combat attribution** writes subsystem damage each hit; this system only *reads* the
  resulting predicates.
- **Established registry pattern.** `engine/appc/hit_vfx.py` (`spawn`/`update_ages`/
  `snapshot`) is the shape this system mirrors — a pure-Python registry pumped once per tick
  from the host loop — but with predicate-gating in place of age-pruning.

## 3. Architecture

A new pure-Python module **`engine/appc/subsystem_emitters.py`** exposing a `PlumeManager`,
driven once per tick from the host loop alongside the existing VFX update. It is the **only**
unit that touches subsystem predicates; combat and the renderer are untouched.

**Components & boundaries:**

| Unit | Responsibility | Depends on |
|---|---|---|
| `PlumeManager` | per-tick scan, state-diff, lifecycle, budget | subsystem predicates, registry, Spec A factory interface |
| registry | `(subsystem_kind, tier) → PlumeDescriptor` table + Python registration API | — (data) |
| `PlumeDescriptor` | factory name + params + direction mode + death-puff flag | — (data) |
| host-loop hook | calls `PlumeManager.update(...)` once per tick | host loop |
| **Spec A (external)** | real controllers behind `Effects.CreateSmokeHigh` / etc. | renderer |

**Per-tick flow** (`PlumeManager.update(ships, camera_pos, dt)`):

1. Iterate each ship's **leaf** damage subsystems that have a registered mapping (warp
   engines, impulse engines, warp core — *not* parent aggregators; plumes need a real
   hardpoint anchor and aggregator state has no single geometry).
2. For each, evaluate current state → resolve to a severity `tier` → look up the registered
   `PlumeDescriptor` for `(subsystem_kind, tier)`.
3. **Diff** against the tracked active-emitter set keyed by `(ship_id, subsystem_id)` and
   apply the transition matrix (§4.2).
4. Apply the **budget** (§4.3) *before* spawning, so suppressed plumes never allocate.

**Why Python, why a manager:** predicate evaluation, state-diffing, and budgeting are policy
— they belong in Python, mirror the `hit_vfx` registry, and stay testable headless (the
project's entire test split depends on a renderer-free logic layer).

## 4. Design decisions (locked in brainstorm; not for relitigation in implementation)

### 4.1 Data model & registration (the mod contract)

The registry is keyed by `(subsystem_kind, tier)` and holds a `PlumeDescriptor`.
`subsystem_kind` is a **stable string token** (`"warp_engine"`, `"impulse_engine"`,
`"warp_core"`, …) derived from the subsystem class — **not** the Python class object — so
mods and save-files never depend on engine class identity. `tier ∈ {DAMAGED, DISABLED}`.
DESTROYED is a one-shot, not a sustained registry row (§4.4).

```python
class DirectionMode:
    FIXED_BODY_VECTOR    = 0   # emit along a fixed body-frame vector (nacelle → aft = (0,-1,0))
    SPHERICAL            = 1   # radiate omnidirectionally (warp-core arcing)
    ALONG_SUBSYSTEM_AXIS = 2   # use the subsystem's own forward axis

@dataclass(frozen=True)
class PlumeDescriptor:
    factory: str            # "CreateSmokeHigh" | "CreateExplosionPlumeHigh" | ... (Spec A names)
    params: dict            # factory kwargs sans the resolved emit frame (velocity, life, size, cone)
    direction_mode: int     # DirectionMode.*
    direction_vec: tuple    # body-frame unit vector, used when FIXED_BODY_VECTOR
    death_puff: str | None  # one-shot factory fired on → DESTROYED transition (None = silent)
    priority_bias: float = 0.0  # optional nudge in the budget sort
```

**Built-in default table** (which factory + direction semantics; exact art values are
tune-by-eye, §7):

| subsystem_kind | DAMAGED | DISABLED | DESTROYED (one-shot) |
|---|---|---|---|
| `warp_engine` (nacelle) | light plasma trail — `CreateSmokeHigh`, thin/fast, aft body-vector | heavy gas plume — `CreateSmokeHigh`, thick/slow, aft body-vector | death puff, then nothing |
| `impulse_engine` | light smoke, aft body-vector | heavy smoke, aft body-vector | death puff |
| `warp_core` | spark + light plasma — `CreateExplosionPlumeHigh` + spark, **SPHERICAL** | heavy spark/arc, SPHERICAL | death puff |
| `shield_generator` | *(no entry)* | *(no entry)* | *(optional death puff or none)* |

No registry entry ⇒ no plume. Shields are simply absent from the table.

**Registration API (exposed to Python for mods):**

```python
subsystem_emitters.register(subsystem_kind, tier, descriptor)        # add/override one cell
subsystem_emitters.register_kind_alias(class_token, subsystem_kind)  # modded class → kind
subsystem_emitters.unregister(subsystem_kind, tier)
```

Mods call these at load time — the same way original BC modders extended `Effects.py`.
Overriding a built-in cell replaces it; registering a new `subsystem_kind` lights up plumes
for a custom subsystem with no engine change. The table is plain, introspectable data.

### 4.2 Lifecycle & transition matrix

`PlumeManager` holds `_active: dict[(ship_id, subsystem_id) → ActiveEmitter]`, where
`ActiveEmitter` records the current `tier`, the live controller handle returned by the
Spec A factory, and a `fading` flag. Each tick it computes `desired_tier`
(`None`/`DAMAGED`/`DISABLED`) and compares:

| From → To | Action |
|---|---|
| none → DAMAGED/DISABLED | spawn controller via mapped factory (budget-permitting) |
| DAMAGED ↔ DISABLED | tear down old (stop-emit + fade), spawn new tier |
| DAMAGED/DISABLED → none (repaired) | **stop-emit, mark `fading`**; controller lives until in-flight particles expire, then drop the handle |
| any → DESTROYED | stop-emit + fade the sustained plume **and** fire the one-shot `death_puff`; mark subsystem terminal so it never re-emits |
| budget-suppressed while active | stop-emit + fade (not a hard kill); re-eligible next tick if budget frees |

**Emit cadence is continuous** while the predicate holds (the SDK
`SetEmitFrequency`/`SetEmitLife` loop, re-armed each tick so the controller never
self-terminates). **"Stop-emit + fade"** = stop re-arming, let `SetEffectLifeTime` run out;
no hard teardown, no pop. The manager releases the handle when the controller reports it has
no live particles left (interface requirement on Spec A, §5).

### 4.3 Budget (large fleet engagements)

Before any spawn, the manager builds the candidate list **per ship**, sorts by
`(tier severity desc, camera proximity desc, priority_bias)`, and admits the top
**`N_per_ship`** (tunable; default ≈ 3). Whole-plume **distance cull**: beyond `R_cull` a
ship emits nothing; in a near/mid band the manager may pass a reduced emit-frequency / LOD
scalar into the factory params (interface-optional, §5.5). Suppressed-but-previously-active
plumes **fade** rather than pop. Worst case is bounded:
`≤ N_per_ship × ships_within_R_cull` controllers.

### 4.4 Severity ladder

- **Damaged → light** continuous plume.
- **Disabled → heavy** continuous plume.
- **Destroyed → one-shot death puff at the transition, then nothing.** The subsystem is gone;
  there is nothing left to vent. The puff is fired through the manager (so it shares the
  plume anchor resolution) but is fire-and-forget — not tracked after spawn.

### 4.5 Anchor & direction

Emit position = `subsystem.GetPosition()` (body-frame hardpoint, world-scale offset). The
manager passes the **body-frame** position plus the resolved direction to the factory; Spec
A's `SetEmitFromObject` + `AttachEffect` keep the emitter glued to the moving ship and
`SetInheritsVelocity(1)` smears particles aft naturally. Direction is **per-mapping data**
(`DirectionMode`): nacelles default to FIXED_BODY_VECTOR aft `(0,-1,0)`; warp core defaults
to SPHERICAL. The manager never does per-frame world math — that lives in Spec A.

### 4.6 Persistence (save/load)

The plume system is **runtime-only** — nothing is serialized, matching every other VFX
system in the project. On load, `PlumeManager` starts empty and **re-derives** all active
plumes from the restored subsystem predicates on the first tick. A subsystem that was
DESTROYED before save loads back destroyed → the manager sees terminal-destroyed and emits
**no** sustained plume and **no** death-puff (the puff fires only on the live *transition*,
which a load is not). Saves restore steady-state plumes without replaying death puffs.

## 5. Interface required from Spec A (the controller backend)

Spec B is written and tested against this contract; Spec A must satisfy it:

1. **Factory functions** matching SDK signatures, returning a controller handle:
   `CreateSmokeHigh(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo)`,
   `CreateExplosionPlumeHigh(fConeAngle, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo)`,
   plus the spark/debris factories the table references.
2. **Emit-from-object semantics** — the controller anchors to a moving ship node
   (`SetEmitFromObject` + `AttachEffect`) and resolves emit origin through the ship's live
   world matrix each frame, so Spec B passes a *body-frame* hardpoint position and never
   touches per-frame world math.
3. **Sustained-loop control** — a controller can be kept emitting indefinitely (re-armed) and
   told to **stop emitting while letting in-flight particles finish**. Spec B needs
   `stop_emitting()` and an `is_finished()` / `has_live_particles()` query to know when to
   release the handle.
4. **Direction input** — accepts an emit direction vector (FIXED_BODY_VECTOR /
   ALONG_SUBSYSTEM_AXIS) and a spherical/omni mode (warp core; maps to SDK
   `SetUpRandomVelocity` / `SetAngleVariance` spread).
5. *(Optional)* an emit-frequency / LOD scalar for distance-band degradation (§4.3).

Spec B ships a thin **`FakeControllerBackend`** test double implementing this interface, so
the state machine, diffing, lifecycle, and budget are fully unit-testable headless — no
renderer, no Spec A.

## 6. Testing (mirrors the project's pure-Python-unit split)

- **State machine:** each §4.2 transition row drives the right backend calls
  (spawn / teardown / fade / death-puff). DAMAGED↔DISABLED swaps the controller;
  repaired→fade (not hard-kill); →DESTROYED fires puff + terminal-no-reemit.
- **Mapping / registry:** built-in table resolves expected factory + direction per
  `(kind, tier)`; `register()` overrides a cell; new `subsystem_kind` lights up;
  unregistered kind (shields) → no spawn; `register_kind_alias` routes a modded class.
- **Anchor / direction:** FIXED_BODY_VECTOR nacelle yields aft `(0,-1,0)` body vector;
  SPHERICAL warp core requests omni spread; body-frame position passes through unmodified
  (no premature world transform).
- **Budget:** with `N_per_ship=3` and 6 damaged subsystems, exactly the 3 highest-priority
  spawn; distance beyond `R_cull` → zero spawns; suppressed-active → fade; bound
  `≤ N × ships` holds.
- **Persistence:** load with a pre-destroyed subsystem → no plume, no death-puff replay; load
  with a disabled subsystem → steady-state heavy plume re-derived on first tick.
- **Host-loop integration:** one `PlumeManager.update(...)` per tick; no calls into
  combat / attribution / renderer beyond the factory interface.

## 7. Parking lot (tune-by-eye)

- Per-tier sprite / colour ramp / velocity / size / cone / emit frequency for each
  `subsystem_kind`.
- `N_per_ship` cap, `R_cull` distance, the near/mid LOD-frequency bands, the budget sort
  weights.
- Whether `shield_generator` gets a DESTROYED death-puff or stays fully silent.
- Whether the warp-core "spark + plasma" is one composite controller or two stacked factory
  calls.

## 8. Non-goals

- **The particle-controller backend itself** — Spec A (separate brainstorm).
- **Hull impact sparks / scorch / emissive flicker** — shipped (`hit_vfx`, decals).
- **Tessellation / mesh smoothing** — separate brainstorm.
- **Bridge-interior smoke / camera shake / panel sparks** — shipped via `hit_feedback.py`.
- **Final art / tuning values** — parking-lot (§7).
- **Save/load of plume state** — runtime-only, re-derived from predicates (§4.6).
- **Rendering of any non-plume effect.**

## 9. Workflow

This spec → one implementation plan via the writing-plans skill →
`docs/superpowers/plans/`, executed via subagent-driven-development. Spec B's logic can be
built and unit-tested immediately against `FakeControllerBackend`; visual bring-up sequences
after Spec A (the controller backend) lands. The two specs share only the §5 interface.
