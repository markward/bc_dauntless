# Impulse-Engine Degradation — Flight Consequences Design

**Status:** spec drafted, awaiting user review
**Date:** 2026-06-10
**Author:** Mark Ward (with Claude)
**Supersedes:** §4.1 ("Engines — linear and angular drag") of
[`2026-06-02-subsystem-failure-consequences-design.md`](./2026-06-02-subsystem-failure-consequences-design.md).
The drag-to-stop model defined there is replaced wholesale by the pod-count
model below. All other gates in that spec (weapons, sensors, shields) are
untouched.

## 1. Goal

Make damage to a ship's individual impulse-engine pods degrade its flight,
proportionally and progressively, instead of having no effect until a
non-targetable master subsystem is disabled.

Two regimes:

1. **Partial loss** — some pods online, at least one offline. Reduce the
   ship's effective max velocity, max acceleration, max angular velocity,
   and max angular acceleration in proportion to the fraction of pods still
   online. A ship that has lost 3 of 4 pods flies at 25% of each limit.
2. **Total loss** — every pod offline (or the master subsystem itself
   offline). The ship **drifts**: it keeps its established world-space
   velocity and its residual angular momentum, with no thrust and no decay,
   until at least one pod is repaired back online.

Applies identically to the player ship and to AI ships.

## 2. Background: how BC models impulse engines

A BC ship carries two distinct things (galaxy hardpoint, `sdk/Build/scripts/
ships/Hardpoints/galaxy.py`):

- **One master `ImpulseEngineSubsystem`** ("Impulse Engines", line 770).
  `SetTargetable(0)` — combat never hits it. It holds the kinematic limits:
  `MaxSpeed`, `MaxAccel`, `MaxAngularVelocity`, `MaxAngularAccel`. This is
  what `ShipClass.GetImpulseEngineSubsystem()` returns.
- **N targetable engine pods** — "Port Impulse", "Star Impulse",
  "Center Impulse" (lines 949–989), each an `EngineProperty` with
  `EngineType == EP_IMPULSE`. `SetTargetable(1)`. These are the things the
  player shoots out.

In our engine (`engine/appc/ships.py:907-944`, Pass 5) the pods are
materialised as plain `ShipSubsystem` leaves and attached as **child
subsystems of the master** via `AddChildSubsystem`. So a ship's impulse
pods are exactly `master.GetChildSubsystem(i)` for
`i in range(master.GetNumChildSubsystems())`.

The current code (`ship_motion.py` and `host_loop.py:_PlayerControl`) gates
only on `_is_offline(master)`, which combat never triggers, and on trigger
drags the ship to a full stop. Both facts are replaced here.

## 2b. SUPERSEDED (2026-07-13) — the derating law is now BC's own

The **shape** of the derating below (§3's first four bullets) was our own
invention, made before we could read the engine. A clean-room decompile of
`stbc.exe`'s `ImpulseEngineSubsystem::GetMaxSpeed` (FUN_00561230) has since
given us the real law, and it differs in two ways:

- **Pods are condition-WEIGHTED, not binary.** BC subtracts, per pod,
  `share = base/n` scaled by `(1 - conditionRatio)`; a *disabled* pod costs its
  entire share. So a pod at 50% health costs half its share and speed bleeds
  continuously — where our binary `online/total` fraction reported a ship with
  three half-dead pods at **full** speed.
- **The power term is the SLIDER, not the received power.** BC multiplies by
  `GetPowerPercentageWanted()` (+0x90), not `received/normal` (+0x94/+0x98). A
  ship whose reactor is starving it still makes its **requested** speed. The
  `[0, base]` clamp lands *before* the multiply, so the slider's 1.25 ceiling
  really does buy 125% of the authored maximum.

Also: BC's **`GetMaxSpeed` is the live, derated value** — the authored figure
lives on the `ImpulseEngineProperty`. `GetCurMaxSpeed` is a *cached* float
(+0xAC) that we model as equal to the live value; its per-tick writer was not
found in the dump, so a spool-up/lerp remains possible (SSDiag.py:114 prints
both as "Maximum/current max speed").

Implemented in `subsystems.impulse_output_fraction`; the four `Get*` limits now
carry the derating themselves, so `ship_motion._effective_motion` no longer
scales them. What **survives** from §3: the drift regime (total pod loss →
inertial coast), the non-braking `_cap_keep` rule, the no-pods → full-capability
fallback, and the all-four-limits-scale-together decision.

## 3. Locked decisions

- **Effectiveness fraction `f` = online pods / total pods.** Linear. No
  weighting by pod size or position. Counted live every tick — repair lifts
  the condition and `f` rises on the next tick with no extra coordination
  (same predicate-at-use-time philosophy as the prior spec).
- **A pod is offline iff `_is_offline(pod)`** — i.e. `IsDisabled()` or
  `IsDestroyed()`. Identical predicate to every other gate.
- **Master offline forces `f = 0`.** If the (non-targetable) master itself
  is ever disabled/destroyed by a script, the whole engine system is dead →
  drift. This preserves a sensible meaning for the old master gate.
- **No pods → `f = 1` (full).** Bare `ShipClass()` test fixtures and any
  ship whose hardpoint declares no `EP_IMPULSE` pods keep full capability;
  the existing `FALLBACK_MAX_ACCEL` snap semantics are untouched. `f` is
  also `1.0` when the master is `None`.
- **All four limits scale by `f`:** max speed, max accel, max angular
  velocity, max angular accel. (User decision: the turn-rate cap scales too,
  not just angular accel.)
- **Caps limit future acceleration; they do not force-brake.** (User
  decision.) A ship already moving faster than its reduced max velocity is
  not dragged down by the cap — it simply cannot accelerate higher. Formally
  the effective target is `min(commanded, max(eff_cap, current))`. Pilot- or
  AI-commanded slowdowns below the cap still work normally; only the *cap
  itself* is non-braking. Same rule applies per-axis to angular velocity.
- **Total loss = inertial drift, replacing drag-to-stop.** The ship keeps
  its **world-space velocity vector** (not its forward axis × speed — the
  velocity is decoupled from facing during drift, so a tumbling ship coasts
  straight) and its residual angular rates. No thrust, no decay. The
  `DISABLED_ENGINE_DRAG_FRACTION` constant and its code paths are deleted.
- **Drift exit re-seeds powered flight.** When a pod returns online, the
  ship leaves drift: `current_speed` is seeded from the drift speed
  (magnitude of the frozen velocity), the drift snapshot is cleared, and the
  normal throttle/setpoint ramp resumes. Velocity direction re-couples to
  facing on the next powered tick — a one-tick direction snap is acceptable
  and not worth modelling away.

## 4. Architecture

### 4.1 Shared effectiveness helper

New module-level function in `engine/appc/subsystems.py`, beside
`_is_offline`:

```python
def impulse_online_fraction(ies) -> float:
    """Fraction in [0, 1] of a ship's impulse engine pods that are online.

    `ies` is the master ImpulseEngineSubsystem (or None). Returns:
      - 1.0 when ies is None or has no child pods (fallback ships);
      - 0.0 when the master itself is offline;
      - online_pods / total_pods otherwise.
    A pod is offline iff _is_offline(pod) (disabled OR destroyed).
    """
    if ies is None:
        return 1.0
    if _is_offline(ies):
        return 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        return 1.0
    online = sum(
        1 for i in range(n) if not _is_offline(ies.GetChildSubsystem(i))
    )
    return online / float(n)
```

This is the single source of truth for "how much engine does this ship
have right now?". Both integrators call it once per tick per ship.

### 4.2 AI integrator — `engine/appc/ship_motion.py`

`_step_ship_motion` is restructured around `f = impulse_online_fraction(
ship.GetImpulseEngineSubsystem())`:

- **`f == 0` (drift):**
  - On *entry* (no active drift snapshot yet), capture
    `ship._drift_velocity = world_dir * ship._current_speed` (a `TGPoint3`,
    the current world velocity). The current `_current_angular_velocity`
    is already the residual angular momentum and needs no snapshot.
  - Each drift tick: advance position by `ship._drift_velocity * dt`;
    advance rotation by `_current_angular_velocity * dt` (the existing
    integration block, but with **no ramp toward the setpoint and no
    decay** — rates are held constant); `SetVelocity(ship._drift_velocity)`.
    Leave `_current_speed` frozen.
- **`0 < f <= 1` (powered):**
  - Clear any drift snapshot. If one existed, seed
    `ship._current_speed = ship._drift_velocity.Length()` before clearing
    (drift-exit re-seed).
  - Scale the limits: `eff_max_speed = f * base_max_speed`,
    `eff_max_accel = f * base_max_accel`,
    `eff_max_ang_vel = f * base_max_ang_vel`,
    `eff_max_ang_accel = f * base_max_ang_accel`, where the `base_*` come
    from the master IES getters. (`f == 1` → identical to today.)
  - Linear target: `target = min(commanded, max(eff_max_speed, current))`
    applied to the forward magnitude, commanded sign preserved. Ramp step
    uses `eff_max_accel` (via `_linear_step_magnitude`, which is updated to
    take an effective MaxAccel).
  - Angular: each axis target clamped per the keep-rule against
    `eff_max_ang_vel`; ramp step uses `eff_max_ang_accel`.

Helper functions `_max_accel`, `_max_angular_accel`, and
`_linear_step_magnitude` are reworked to accept/apply the effective
(`f`-scaled) values rather than the raw IES getters. Fallback ships
(`ies is None` or `MaxSpeed == 0`) keep `FALLBACK_MAX_ACCEL` and `f == 1`,
so existing snap-to-target tests are byte-unchanged.

### 4.3 Player integrator — `engine/host_loop.py:_PlayerControl`

Mirror of 4.2, against `self._get_ies(player)`:

- `f = impulse_online_fraction(ies)` computed once at the top of `apply`.
- **`f == 0` (drift):** snapshot `self._drift_velocity = R.GetCol(1) *
  self._current_speed` on entry; each drift tick integrate position by
  `self._drift_velocity` (world, **not** recomputed from facing) and
  integrate rotation using the *current* pitch/yaw/roll rates held constant
  (skip the ramp-to-zero). Throttle keys are still read (so the queued
  impulse level is remembered) but do not affect motion until drift exits.
- **`0 < f <= 1` (powered):** clear drift (seeding `_current_speed` from
  `_drift_velocity.Length()` on exit); scale `eff_max_*` by `f`;
  - `GetTargetSpeed` loses its `_is_offline → 0.0` early-out (drift is now
    handled in `apply`, not by zeroing the target). It returns the
    throttle-commanded speed against the **base** max (unscaled) — the cap
    is enforced by the keep-rule clamp in `apply`, not by shrinking the
    target, so a ship above its reduced cap is not braked.
  - Linear keep-rule clamp + `eff_max_accel` ramp step.
  - `_angular_rate` returns `f * base_max_ang_vel`; the per-axis key targets
    are clamped by the keep-rule; `_angular_accel` ramp step uses
    `f * base_max_ang_accel`.

### 4.4 Removed code

- `DISABLED_ENGINE_DRAG_FRACTION` (constant + every multiply site in both
  files).
- The `engines_offline` drag branches in `_step_ship_motion` and
  `_PlayerControl.apply`.
- The `_is_offline(ies) → return 0.0` early-out in `GetTargetSpeed`.

## 5. Data / state

- `ship._drift_velocity` / `_PlayerControl._drift_velocity`: `TGPoint3 |
  None`. `None` ⇒ powered flight. Set on drift entry, cleared on exit.
- Must round-trip through save/load. AI ships persist via
  `__getstate__/__setstate__`; add `_drift_velocity` to the persisted state
  the same way `_current_speed` / `_current_angular_velocity` are handled.
  (Verify during implementation; if `_current_speed` is reconstructed rather
  than pickled, drift snapshot follows the same policy — a ship reloaded
  mid-drift may resume powered, which is acceptable.)

## 6. Testing

Unit (`tests/unit/`):

- `impulse_online_fraction`: no IES → 1.0; master offline → 0.0; 0/3/4 pods
  offline → 1.0 / 0.25 / 0.0 etc.; no pods → 1.0.
- Partial-loss scaling on a Galaxy: disable 1 of 3 pods, assert the ship's
  effective max speed / accel / angular limits are 2/3 of base (probe via a
  few ramp ticks reaching the reduced cap).
- Keep-rule: ship cruising above the reduced cap is **not** braked by the
  cap; ship below the cap accelerates only up to it.

Integration (`tests/integration/`):

- **Rewrite** `test_engines_disabled_decays_velocity.py` → drift, not decay:
  disable all pods, assert constant velocity over many ticks (no decay),
  then repair one pod and assert powered flight resumes.
- Drift-while-tumbling: give a ship residual angular velocity, drop all
  pods, assert position advances in a straight world-space line while the
  ship's rotation keeps changing (velocity decoupled from facing).
- Partial-loss end-to-end through `_step_ship_motion`: 2 of 4 pods offline →
  ship tops out at ~50% max speed.

Player-path coverage mirrors the AI cases against `_PlayerControl.apply`
with a fake host (`tests/unit/test_player.py` style).

## 7. Out of scope

- Per-pod asymmetric thrust (losing a port engine inducing yaw). Pods are
  pooled into a single scalar fraction.
- Warp-engine degradation. Only impulse (`EP_IMPULSE`) pods are counted.
- Any change to weapons / sensors / shield gates from the prior spec.
- A real drag/physical-damping model. Powered flight uses the existing
  rate-limited asymptote ramp; drift is pure inertia.
