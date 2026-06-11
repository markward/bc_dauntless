# Particle Backend A3 — sparks/debris + unified spark rendering (Spec A, slice 3)

**Status:** drafted, awaiting user review
**Date:** 2026-06-11
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-11-particle-backend-a1-smoke-design.md`](./2026-06-11-particle-backend-a1-smoke-design.md) — **A1**, the stateless-analytic billboard particle renderer (`ParticlePass`) + `AnimTSParticleController` + registry. A3 extends the same pass and controller.
- **A2 (merged to main, implemented directly without a spec doc)** — per-emitter additive blend, emit-radius, 3D random velocity; the `ExplosionPlumeController` alias made real; explosion/puff/weapon/death factories run SDK-unmodified. A2's death sequence (`CreateObjectExplosion`/`ObjectExploding`) calls `CreateDebrisSparks`, which today registers a `_NamedStub` (silent no-op). **A3 closes that gap.**
- `native/src/renderer/hit_vfx_pass.cc` — A1's existing **procedural one-shot impact sparks** (heavy-hit burst, damped ballistic billboards, `kSparkDamping`/`kSparkSpeed`/`kSparkLife`, `rough.tga`, hull-anchored via `instance_id`). A3 **reconciles** these to the unified spark look (shared rendering; trigger untouched).
- SDK `sdk/Build/scripts/Effects.py` — `CreateWeaponSparks` (329), `CreateDebrisSparks` (457). **Bodies not rewritten** — A3 makes the `SparkParticleController` primitive they call real.

## 0. Where A3 sits

A3 is the third and final slice of the Spec A particle program (A1 smoke / A2 explosion-plume / **A3 sparks**). It un-stubs the last particle family. After A3, every particle factory the SDK `Effects.py` references is backed by a real renderer-driven controller, and A2's death sequence renders its debris sparks instead of silently dropping them.

A3 is a **clean, tight slice** — no Phase-1 orchestration walls (those belong to the deferred engine timed-sequencing project, see §8). The two new capabilities are pure additive extensions of the A1/A2 `ParticlePass`.

## 1. Two new particle capabilities (both additive)

When both are at their defaults, the render output is byte-identical to A1/A2 (existing GL tests must stay green).

| Capability | Descriptor field | Effect |
|---|---|---|
| **Velocity damping** | `damping` (default 0 = none) | directed travel follows the analytic damped curve `(v/c)(1−e^{−cτ})` instead of linear `v·τ` — the ballistic decay sparks need. This is exactly the formula `hit_vfx_pass` already uses (`kSparkDamping`). |
| **Tail / streak** | `tail_length` (default 0 = billboard) | the particle quad is stretched along the particle's instantaneous velocity axis into a motion streak (length ∝ `tail_length`·speed), instead of a camera-facing square. The one genuinely new draw mode. |

## 2. The analytic spark model

The whole system stays stateless-analytic: every particle's state is computed from the descriptor + per-particle hash, no per-particle storage.

### 2.1 Damped travel (`particle_math.h`, pure/GL-free)

```cpp
inline float damped_travel(float v, float c, float tau) {
    return (c > 1e-6f) ? (v / c) * (1.0f - std::exp(-c * tau)) : v * tau;
}
```

The directed displacement in `particle_world_pos` changes from `dir * (emit_velocity * tau)` to `dir * damped_travel(emit_velocity, damping, tau)`. The A2 velocity-inherited trail and 3D-random-velocity terms remain; when `damping>0` the random-velocity term is damped too (sparks slow uniformly). `damping=0` ⇒ linear ⇒ A1/A2 unaffected.

### 2.2 Analytic velocity (needed for the streak axis)

Because position is analytic, velocity is its derivative. The directed component is `dir · emit_velocity · e^{−c·τ}` (plus the damped random/inherit contributions). The pass computes this per particle; its normalized form is the streak axis. At `τ=0` the streak points along the full emit direction; as the spark slows the streak shortens — automatically.

### 2.3 Streak geometry (`particle_math.h` builder + the pass)

When `tail_length>0`, the pass builds a **velocity-aligned billboarded quad** instead of a camera-facing square:
- long edge = `normalize(vel_axis) · (tail_length · speed)` (the streak length),
- short edge = `normalize(cross(view_dir, vel_axis)) · size` (camera-facing half-width),
so the streak reads as a line from any camera angle. `tail_length=0` collapses the long edge to `size` → the existing camera-facing square (A1 path, unchanged).

A pure helper `streak_quad(center, vel_axis, length, half_width, cam_right, cam_up/view_dir)` returns the four corners; it is unit-tested without GL and is **the shared primitive both `ParticlePass` and `hit_vfx_pass` call** (§4).

## 3. Components

| Unit | Change |
|---|---|
| `native/src/renderer/include/renderer/frame.h` | add `float damping = 0.0f;` + `float tail_length = 0.0f;` to `ParticleEmitterDescriptor`. |
| `native/src/renderer/include/renderer/particle_math.h` | add `damped_travel` + `streak_quad` pure helpers; use `damped_travel` in `particle_world_pos` (or a sibling). |
| `native/src/renderer/particle_pass.cc` | per particle: damped travel; when `tail_length>0`, draw the velocity-aligned streak quad via `streak_quad`. |
| `native/src/host/host_bindings.cc` | read `damping` + `tail_length` dict keys (guarded defaults). |
| `native/src/renderer/hit_vfx_pass.cc` | **reconcile**: route the spark sub-quad draw through the shared `streak_quad` + `damped_travel`. Trigger/anchoring/`spark_count`/tint/lifetime unchanged. |
| `engine/appc/particles.py` | `SparkParticleController(AnimTSParticleController)` + `SparkParticleController_Create(total_life, duration, emit_rate)`; real `SetDamping`/`SetTailLength`; `_descriptor_for` emits `damping`/`tail_length`. |
| `App.py` | wire `SparkParticleController_Create`. |
| SDK `Effects.py` | unchanged — `CreateWeaponSparks`/`CreateDebrisSparks` run as written. |

### 3.1 `SparkParticleController`

```python
class SparkParticleController(AnimTSParticleController):
    def __init__(self, total_life=1.0, duration=1.0, emit_rate=0.005):
        super().__init__()
        self._effect_life_time = total_life   # emitter total life (ctor arg 1)
        self._emit_frequency = emit_rate      # emit cadence (ctor arg 3)
        self._duration = duration             # emission window (ctor arg 2)
        self._damping = 0.0
        self._tail_length = 0.0

    def SetDamping(self, d):    self._damping = d
    def SetTailLength(self, l): self._tail_length = l


def SparkParticleController_Create(total_life=1.0, duration=1.0, emit_rate=0.005):
    return SparkParticleController(total_life, duration, emit_rate)
```

It inherits every other SDK setter from `AnimTSParticleController` (all already real). `_descriptor_for` gains `"damping": float(c._damping)` and `"tail_length": float(c._tail_length)`, defaulting to `0.0` via `getattr(c, "_damping", 0.0)` so non-spark controllers emit zeros (and stay on the A1/A2 path).

### 3.2 The `duration` → emission-window mapping

The SDK passes `(total_life, duration, emit_rate)`: the emitter emits for `duration`, then in-flight sparks finish out to `total_life`. This maps cleanly onto the existing analytic `stop_age`/`EffectLifeTime` machinery: emission ceases at `duration` (fold `duration` into the controller's effective emission cutoff, i.e. `stop_age = min(explicit stop, duration)`), and the controller lives until `total_life` (`_effect_life_time`). No new mechanism — the A1 analytic stop/fade already does exactly this.

### 3.3 Payoff (no A2/Spec-B code changes)

Once `SparkParticleController_Create` is real, A2's `CreateObjectExplosion`/`ObjectExploding` (which call `CreateDebrisSparks`) register real tailed sparks instead of a `_NamedStub`. The death visual gains debris sparks automatically. No edits to A2 or Spec B.

## 4. `hit_vfx` reconciliation (shared rendering; trigger preserved)

The accepted-blast-radius item: A1's one-shot impact sparks become visually identical to A3's debris sparks by sharing the render primitive.

- **Change:** replace the per-spark *draw* in `hit_vfx_pass.cc`'s spark loop with the shared `streak_quad(...)` call, with `vel_axis` = the spark's analytic velocity direction and `length` = `kSparkTailLength` × current speed. Confirm its damped travel routes through `damped_travel(kSparkSpeed, kSparkDamping, age)` (it already matches numerically).
- **Unchanged:** the heavy-hit/CRITICAL trigger, `spark_count`, hull-anchoring via `instance_id`, per-weapon tint/cone, spark lifetime, and the separate impact-flash billboard.
- **Consequence (accepted):** impact-burst sparks change from round billboard points to tailed streaks — consistent with debris sparks. This is a deliberate visual change to shipped impact feedback, scoped to the spark sub-quad only.

This is the bounded interpretation of "reconcile": **share the look, not the trigger.** Retiring the `hit_vfx` spark trigger/descriptor system and routing impacts through the `ParticleEmitterDescriptor` pipeline is explicitly a non-goal (§8).

## 5. Testing

Project split: pure unit (Python + GL-free C++) + offscreen `FrameTest`.

**C++ math (no GL) — `particle_math_test.cc`:**
1. `damped_travel(v, c, τ)` matches the curve for `c>0`; equals `v·τ` at `c=0`; monotonic increasing in τ; asymptotes to `v/c`.
2. `streak_quad` at `length=0` degenerates to the existing camera-facing square (corners match the A1 quad); at `length>0` its long edge is parallel to `vel_axis` and its short edge is camera-facing (perpendicular to both `vel_axis` and view).

**Renderer `FrameTest` (llvmpipe; skips without assets):**
3. A `tail_length>0` emitter renders stretched quads; the streak of a damped spark shortens as τ grows (slower → shorter).
4. A `damping>0` emitter's particle travel matches `damped_travel` within tolerance.
5. `tail_length=0 && damping=0` → byte-identical to the A1 baseline frame.
6. `hit_vfx` sparks render as streaks with `GL_NO_ERROR`; the existing `hit_vfx`/`ParticlePass` GL tests still pass (re-baselined for the streak look where they checked spark shape — they assert presence + `GL_NO_ERROR`, not exact pixels).

**Python — `tests/unit/test_particles_spark.py`:**
7. `SparkParticleController` setters round-trip; the 3-arg constructor maps `(total_life→_effect_life_time, emit_rate→_emit_frequency, duration→_duration)`.
8. `_descriptor_for` emits `damping`/`tail_length` for a spark controller and `0.0`/`0.0` for a plain `AnimTSParticleController` (non-spark emitters unaffected).
9. **SDK-unmodified proof:** `Effects.CreateWeaponSparks(...)` and `Effects.CreateDebrisSparks(...)` build a real `SparkParticleController` with the SDK's tail/damping/keys and register it; **no `SparkParticleController_Create` stub rows** in `App._stub_tracker`.
10. **End-to-end:** `Effects.ObjectExploding(fake)` now registers ≥1 real `SparkParticleController` (the A2 death-probe debris gap closes); the A2 death-probe test that documented the silent-stub debris is updated to assert real sparks.

## 6. Non-goals / parking-lot

- **Retiring the `hit_vfx` spark trigger system** — A3 shares rendering only (§4).
- **Death-cascade timing** — still the deferred engine timed-sequencing project (§8); A3 makes deaths render debris sparks, but the multiple explosions still fire simultaneously under the Phase-1 synchronous action model.
- **Final art/tuning** — tail length, sprites (`rough.tga`/`smooth.tga`), damping constants, the `hit_vfx` streak length — tune-by-eye.
- **Spec-B warp-core spark layer** — now possible (real sparks exist); left as a later table-tuning option, not part of A3.
- **Spark/debris callers beyond the two factories** (e.g. `CreateCollisionExplosion` debris) — they work once the controller is real, but aren't separately tested here.
- **Save/load** — runtime-only, as with all particle VFX.

## 7. Production safety

A3 is strictly additive: with `damping=0`/`tail_length=0`, the `ParticlePass` is byte-identical to A1/A2 (proven by test 5). The only non-additive change is the deliberate `hit_vfx` spark-shape reconciliation (§4), gated to the spark sub-quad and re-baselined in its GL tests. `SparkParticleController_Create` replaces a `_NamedStub` that silently dropped sparks, so it can only add rendering, never remove behavior. m3gameflow and the A2 death sequence must stay green (deaths now additionally render real sparks).

## 8. Workflow

This spec → one implementation plan (writing-plans) → `docs/superpowers/plans/`, executed via subagent-driven-development. Suggested order: (1) `damped_travel` + `streak_quad` math + tests; (2) `ParticlePass` damping + streak draw; (3) host binding fields; (4) `SparkParticleController` + factories + App wiring + SDK-unmodified proof; (5) `hit_vfx` reconciliation + re-baseline; (6) end-to-end death-sequence debris test. A3 is the last particle slice; the **engine timed-sequencing project** (making the death cascade stagger over time) remains separate and demand-driven — A3 does not touch `actions.py`.
