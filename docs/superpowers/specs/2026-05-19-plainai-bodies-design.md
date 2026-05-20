# PlainAI Body Ports (Slice D2)

**Status:** spec — awaiting plan.
**Predecessors:** Slice A (BuilderAI + ConditionScript), Slice B (SelectTarget), Slice C (FireScript), Slice D1 (sub-Compound activation smokes — merged at `78555aa`).
**Follow-on:** Slice E (NonFedAttack/FedAttack visible mission).

## Goal

Make the 5 PlainAI script bodies that NonFedAttack/FedAttack instantiate via `SetScriptModule(...)` actually drive ship motion. End state: a ship under NonFedAttack chases its target, turns to face, fires torpedoes on approach — the activation-only behaviour from Slice D1 becomes observable kinematic + weapon behaviour. The xpassing NonFedAttack smoke from Slice C flips to passing cleanly with tightened assertions.

## Scope

The 5 PlainAI scripts:
- `TorpedoRun` (~239 LOC) — torpedo-run motion: predict target intercept point via torp launch speed, fuzzy-speed control by distance + facing, turn toward predicted location.
- `StationaryAttack` (~143 LOC) — hold position; turn toward target's predicted location.
- `IntelligentCircleObject` (~392 LOC) — orbit target with shield-bias + weapon-arc orientation. Most elaborate.
- `FollowObject` (~182 LOC) — follow another ship with fuzzy distance-based speed control.
- `Intercept` polish (~367 LOC) — Slice A landed an initial port; identify and fill behaviour gaps surfaced by NonFedAttack/FedAttack usage.

**End state:** all 5 scripts have integration tests pinning observable behaviour. Existing NonFedAttack xpass smoke flips to passing cleanly with tightened assertions (ship speed/turn/fire over multiple ticks).

## Architecture

PlainAI scripts load via `_SDKFinder` unchanged. Each subclasses `BaseAI.BaseAI` and defines its own `Update()` body. Slice D2's work is filling in engine surface so those Update bodies execute correctly and drive observable ship state changes.

The pattern (established by Slice A's `GoForward`/`Stay`/`Intercept` ports):
1. SDK script loads via `_SDKFinder`.
2. Mission/test code instantiates a `PlainAI` via `App.PlainAI_Create(pShip, name)`, calls `SetScriptModule(<script>)`, then sets parameters via `GetScriptInstance().SetX(...)`.
3. `tick_ai` walks the AI tree; when it reaches the PlainAI, it calls the script instance's `Update()` (cadence controlled by `GetNextUpdateTime()`).
4. `Update()` reads ship state via `pShip.GetWorldLocation()`, `GetVelocityTG()`, etc., computes a setpoint, and writes back via `pShip.SetSpeed(...)`, `SetImpulse(...)`, `TurnTowardLocation(...)`, etc.

D2's work is making step 4 actually work for the 5 scripts.

## Components

### FuzzyLogic helpers (`App.py`)

The biggest engine addition. SDK pattern, function form:
```python
fNearSet, fMidSet, fFarSet = App.FuzzyLogic_BreakIntoSets(value, (loThresh, midThresh, hiThresh))
```
Returns three floats summing to 1.0 representing memberships in "low", "mid", "high" sets — trapezoidal/triangular curves between the thresholds. Used by TorpedoRun + FollowObject.

SDK pattern, class form:
```python
pFuzzy = App.FuzzyLogic()
pFuzzy.AddInput(name, value)
pFuzzy.AddOutput(name)
pFuzzy.AddRule(...)
fOut = pFuzzy.Evaluate(name)
```
Used by IntelligentCircleObject. More elaborate; the plan reads the actual SDK call sites and decides whether to port the full class or stub the methods to plausible defaults. The visible-mission end state requires "ship behaves plausibly," not pixel-perfect SDK fidelity.

### Ammo accessor (`engine/appc/subsystems.py`)

`TorpedoAmmoType.GetLaunchSpeed() -> float` — single-line method exposing the existing `_launch_speed` field. Used by TorpedoRun + StationaryAttack to predict torpedo intercept points.

### Matrix/vector helpers

- `TGMatrix3.Transpose()` — used by IntelligentCircleObject. Add if currently missing.
- `TGPoint3.MultMatrixLeft` already exists (used by `engine/appc/subsystems.py:38, 67, 96`).

### Shield directional constants

`App.ShieldClass.TOP_SHIELDS`/`LEFT_SHIELDS`/`RIGHT_SHIELDS`/`BOTTOM_SHIELDS` — referenced by IntelligentCircleObject. Verify they exist on the engine `ShieldClass`; add as class attributes with the SDK's int values if missing. `pShields.GetCurShields(direction)` accessor — verify.

### Integration test files

| File | Asserts |
|---|---|
| `tests/integration/test_torpedo_run_smoke.py` | After `Update()`: ship's `_speed_setpoint[0]` non-zero; `TurnTowardLocation` reached the target's predicted location. |
| `tests/integration/test_stationary_attack_smoke.py` | Ship's `_speed_setpoint[0]` is 0.0; `TurnTowardLocation` reached the target's predicted location. |
| `tests/integration/test_follow_object_smoke.py` | At various distances (near/mid/far), speed setpoint matches fuzzy expected range. |
| `tests/integration/test_intelligent_circle_object_smoke.py` | Ship's speed/turn updated; orbit-angle computation doesn't crash. |
| `tests/integration/test_intercept_polish_smoke.py` | Existing Slice A `test_ai_intercept_smoke.py` still passes; new assertions about combat-relevant Intercept behaviour. |

### Tightened NonFedAttack smoke (Task 7)

Existing `tests/integration/test_non_fed_attack_smoke.py` is currently xfail-marked but xpasses. With D2 making the 5 PlainAI bodies behave, the smoke can flip to a real passing test. Task 7 removes the `xfail` marker and adds stronger assertions: tick 5-10 times, assert (a) ship's speed setpoint changes across ticks, (b) `TurnTowardLocation` was called at least once with the target's location, (c) some weapon's `StartFiring` was reached.

## Data flow

```
tick_ai(non_fed_attack_root, game_time)
  └─ walks tree → reaches PlainAI nodes (TorpedoRun, StationaryAttack, etc.)
       └─ each PlainAI's _next_update_time gates Update() at cadence
       └─ Update() body:
            ├─ pShip = self.pCodeAI.GetShip()
            ├─ pTarget = App.ObjectClass_GetObject(pSet, self.sTarget)
            ├─ pTarget.GetWorldLocation() + pShip.GetWorldLocation() → vDifference, fDistance, vDirection, fAngle
            ├─ App.FuzzyLogic_BreakIntoSets(fDistance, ...) → membership weights
            ├─ compute fSpeed, vTurnTarget from fuzzy weights
            ├─ pShip.SetSpeed(fSpeed, vDir, DIRECTION_MODEL_SPACE)
            └─ pShip.TurnTowardLocation(vTurnTarget)
```

Cross-script consistency: each script writes to the ship's `_speed_setpoint` tuple and `_angular_velocity_setpoint` via the existing motion methods Slice A landed. The per-tick `ship_motion` pass then integrates those setpoints into the ship's world transform.

## Error handling

Consistent with Slices A-D1:

- **Engine surface is permissive.** Missing accessors return safe sentinels.
- **Engine-gap escalation.** Trivial gaps → separate `feat(<module>): <what>` commits BEFORE the test commit. Novel gaps → STOP and report.
- **SDK scripts load unmodified.**
- **FuzzyLogic semantics:** if we can't infer the exact membership-curve shape from SDK callers, implement a sensible interpretation (e.g., triangular sets with overlap at the midpoint thresholds) and document the choice in the engine source. The visible smoke doesn't require pixel-perfect SDK matching.
- **Test isolation autouse fixtures** clear `g_kSetManager._sets` + `g_kEventManager._method_handlers`. Do NOT clear `_broadcast_handlers`.

## Testing strategy

7 tasks:

1. **`FuzzyLogic_BreakIntoSets` + `FuzzyLogic` class** — prerequisite engine surface. Unit tests pin membership-curve outputs at boundary values + class round-trip. Used by Tasks 2, 4, 5.
2. **TorpedoRun smoke** — full kinematic path: target prediction via torp launch speed, fuzzy speed/turn, `TurnTowardLocation`. May surface `GetLaunchSpeed` accessor as a separate `feat(...)` commit.
3. **StationaryAttack smoke** — simpler: hold position, turn toward predicted target. Shares `GetLaunchSpeed` (already landed in Task 2).
4. **FollowObject smoke** — fuzzy distance → speed. Uses `FuzzyLogic_BreakIntoSets` from Task 1.
5. **IntelligentCircleObject smoke** — most elaborate. Uses `FuzzyLogic()` class form + shield-directional constants + matrix `Transpose`. Surfaces 1-2 more engine commits likely.
6. **Intercept polish smoke** — re-verify Slice A `test_ai_intercept_smoke.py` plus add combat-relevant assertions.
7. **Tighten NonFedAttack smoke + close deferred doc** — remove `xfail`, add behaviour assertions across multiple ticks; mark Slice D2 ✅ in `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`; forward-ref Slice E.

## Out of scope (deferred to E)

- `NonFedAttack`/`FedAttack` `CreateAI` polish beyond what the existing xpass smoke catches.
- Visible mission scripting (E1M1 or new BasicAttack mission). Slice E.
- `AvoidObstacles` preprocessor port — Compound trees use it but it's not in the 5-script D2 scope.
- `OptimizedTorpedoRun` / similar C-backed replacements — never; we run the Python.

These remain noted in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
