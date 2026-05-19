# FireScript Preprocessor (BasicAttack Slice C)

**Status:** spec — awaiting plan.
**Predecessors:** Slice A (BuilderAI + ConditionScript), Slice B (SelectTarget preprocessor — merged at `ea1463f`).
**Follow-ons:** Slice D (PlainAI sub-graphs), Slice E (FedAttack/NonFedAttack `CreateAI` assembly + visible smoke).

## Goal

Port `FireScript` from `sdk/Build/scripts/AI/Preprocessors.py:36-1057` to the headless engine so an AI-driven ship can cycle weapon systems, pick a target subsystem, and fire phasers/torpedoes at the target SelectTarget propagated. Slice C closes the loop "AI sees target → weapon fires → target's hull takes damage" end-to-end through the existing combat path.

## Scope

**Pragmatic mid-scope:** port FireScript's per-tick driver (`Update`), weapon registration (`AddWeaponSystem`), the firing path (`FireSystemAtTarget` + `ConfigureWeaponSystem`), and a basic subsystem-targeting brain (`ChooseTargetSubsystem`, `RateSubsystemForTargeting`, `PickTargetSubsystemFromList`, `GetTargetableSubsystems`). Include a basic `PredictTargetLocation` (stub: fire at current position). Skip the tactical-depth methods listed under "Out of scope".

**End state:** integration test where a ship under `SelectTarget + FireScript` actually fires at the chosen target and the target takes damage through the existing `ET_WEAPON_HIT` combat path.

## Architecture

FireScript ports as a Python class loaded via `_SDKFinder` from `sdk/Build/scripts/AI/Preprocessors.py:36-1057`, mirroring the SelectTarget pattern from Slice B. It runs as a `PreprocessingAI` — same AI primitive as SelectTarget. Multiple preprocessors can be chained per ship by wrapping a `PriorityListAI` whose contained AI itself wraps a `PreprocessingAI`. Each tick, `tick_ai` dispatches `FireScript.Update(dEndTime)` via the arity-introspected preprocess driver from Slice B's Task 1.

FireScript holds a list of `WeaponSystem` instances added via `AddWeaponSystem`, plus configuration: subsystem target priorities, torp-firing flags, phaser power policy, dumb-fire mode. Per tick, `Update` walks an `iLastUpdate` counter that cycles through: target-visibility check (frame -2), subsystem selection (frame -1), then weapon-N firing (frames 0..len(lWeapons)-1). The cycle counter is `iLastUpdate = ((iLastUpdate + 3) % (N+2)) - 2`. With 2 weapons the sequence over 4 ticks is `-2, -1, 0, 1` then repeats.

### Surface boundaries

| File | Additions |
|---|---|
| `engine/appc/subsystems.py` | `PhaserSystem.SetPowerLevel`/`GetPowerLevel` + `PP_LOW`/`PP_HIGH`; `TorpedoSystem.GetNumAmmoTypes`/`GetAmmoType`/`GetCurrentAmmoType`/`SetCurrentAmmoType`/`GetAmmoCount`; `TorpedoTube.FireDumb`/`CalculateRoughDirection`; `WeaponSystem.StopFiringAtTarget`; `ImpulseEngine.GetCurMaxSpeed` (confirm existence). |
| `engine/appc/ai_driver.py` | First-tick `CodeAISet` analog for FireScript (mirrors Slice B Task 9's SelectTarget pattern). Duck-typed gate: `DamageEvent` method + `lWeapons` attribute (distinguishes from SelectTarget which has `DamageEvent` but no `lWeapons`). |
| `App.py` | `PhaserSystem_Cast`, `TorpedoSystem_Cast`, `TractorBeamSystem_Cast`, `ShipSubsystem_Cast`, `TGObject_GetTGObjectPtr` (round-trip via existing ID registry). |
| `engine/appc/ships.py` | Confirm `GetImpulseEngineSubsystem` exists (it does, line 427). |

### SDK script loads unmodified

The 1022-line FireScript class at `sdk/Build/scripts/AI/Preprocessors.py:36-1057` loads via `_SDKFinder` and runs as-is. Nothing in `sdk/` is forked. Any crash is fixed engine-side.

## Components

### 1. Weapon-system casts (`App.py`)

`isinstance`-based, four lines each, mirror `ObjectClass_Cast`:
- `PhaserSystem_Cast(o) → PhaserSystem | None`
- `TorpedoSystem_Cast(o) → TorpedoSystem | None`
- `TractorBeamSystem_Cast(o) → TractorBeamSystem | None`
- `ShipSubsystem_Cast(o) → ShipSubsystem | None`

### 2. Phaser power model (`subsystems.py`)

`PhaserSystem.PP_LOW = 0`, `PP_HIGH = 1` class constants. `SetPowerLevel(level)` and `GetPowerLevel() → int` store/return state. No kinematic effect in Phase 1 — combat damage multiplier hooked later if/when needed for Slice E balance.

### 3. Torpedo ammo + types (`subsystems.py`)

`TorpedoSystem.GetNumAmmoTypes() → int` defaults to 1. `GetAmmoType(i) → int` returns type-id (default `[0]`). `GetCurrentAmmoType() → int`, `SetCurrentAmmoType(t)`. `GetAmmoCount(t) → int` defaults to a large value (infinite for tests unless explicitly populated). Sufficient to exercise `ChooseTorpType` without modeling ammo depletion.

### 4. TorpedoTube extensions (`subsystems.py`)

`FireDumb(reserved=0, force=1)` calls the existing `Fire(target=None)` path — dumb-fire and locked-fire route through the same `ET_WEAPON_HIT` broadcast in Phase 1. `CalculateRoughDirection() → TGPoint3` returns the parent ship's forward vector (per-tube arcs deferred to D/E). `WeaponSystem.StopFiringAtTarget(pTarget)` aliases `StopFiring()` since headless doesn't track multi-target firing state.

### 5. ImpulseEngine.GetCurMaxSpeed (`subsystems.py`)

Returns the current speed cap based on the engine's power level. Used by `FireScript.ConfigureWeaponSystem` to pass `fTargetSpeed` into `ChooseTorpType`. Confirm existing surface; add if missing.

### 6. TGObject id round-trip (`App.py`)

`TGObject_GetTGObjectPtr(obj_id) → obj | None` looks up via the existing object ID registry. The combo `App.ShipSubsystem_Cast(App.TGObject_GetTGObjectPtr(id))` is how FireScript round-trips the cached subsystem ID across ticks (`Update` line 326).

### 7. ai_driver first-tick FireScript CodeAISet (`ai_driver.py`)

Mirrors Slice B Task 9's SelectTarget pattern. SDK `CodeAISet` at `Preprocessors.py:137-145` shows what to wire for FireScript: `pEventHandler = TGPythonInstanceWrapper(self)`, broadcast handler registration for `ET_WEAPON_HIT` routed to `DamageEvent` keyed on `pCodeAI.GetShip()`. Idempotent via `_dauntless_codeaiset_done` sentinel. Duck-typed gate: `callable(DamageEvent)` AND `hasattr(inst, "lWeapons")` — `lWeapons` distinguishes FireScript from SelectTarget (which also has `DamageEvent` but no weapon list).

## Data flow

```
tick_ai(root_ai, game_time)
  └─ _tick_preprocessing(pp_firescript, ...)
       ├─ FIRST TICK ONLY: _ensure_firescript_initialized(inst)
       │    ├─ inst.pEventHandler = TGPythonInstanceWrapper(inst)
       │    ├─ AddBroadcastPythonMethodHandler(ET_WEAPON_HIT, ..., target=ship)
       │    └─ inst._dauntless_codeaiset_done = True
       └─ inst.Update(dEndTime)                  ← SDK Python, unmodified
            │
            ├─ pTarget = inst.GetTarget()        → resolves inst.sTarget via ship's set
            ├─ iLastUpdate==-2: TargetVisible(pTarget) → bTargetVisible
            ├─ iLastUpdate==-1: ChooseTargetSubsystem(pTarget)
            │                     └─ rates subsystems via RateSubsystemForTargeting
            └─ iLastUpdate>=0: FireSystemAtTarget(lWeapons[i % N], pTarget, pSubsystem)
                 ├─ ConfigureWeaponSystem(weapon, target, subsystem)
                 │    ├─ PhaserSystem_Cast → SetPowerLevel(PP_LOW|PP_HIGH)
                 │    └─ TorpedoSystem_Cast → ChooseTorpType (if bChooseTorpsWisely)
                 └─ CheckGoodShot → True (stub) → weapon.StartFiring(target, offset)
                       └─ engine combat path emits ET_WEAPON_HIT → target's hull damage
```

### Cross-preprocessor coupling with SelectTarget

FireScript receives its target two ways:

1. **Direct string** via `inst.sTarget` on construction (NonFedAttack pattern: `FireScript(sInitialTarget, ...)`). Resolved via `GetTarget()` → `pShip.GetContainingSet().GetObject(sTarget)`.
2. **Dispatched** when SelectTarget picks: SelectTarget walks `GetAllAIsInTree()[1:]` and calls `CallExternalFunction("SetTarget", chosen_name)` on every AI. FireScript registers `SetTarget` as an external function → its own `SetTarget(sName)` method updates `inst.sTarget`. The Slice B dispatch wiring already works for PreprocessingAI nodes because `CallExternalFunction` lives on `ArtificialIntelligence` base (Slice B Task 8 commit `737c1d0`).

### Damage event

The broadcast handler registered in CodeAISet routes incoming `ET_WEAPON_HIT` to `FireScript.DamageEvent`. The SDK uses this to update tactical state. For Slice C the handler runs but its only observable assertion is "doesn't crash" — full event-driven retargeting is downstream tactical brain we deferred.

## Error handling

Consistent with Slice B:

- **Engine surface is permissive.** Casts return None for non-matches. Missing accessors return safe sentinels (`0`, `0.0`, `()`, `None`). The SDK code is already defensive — we don't double-guard.
- **Engine-gap escalation.** Trivial single-line stubs land as separate `feat(<module>): <what>` commits before any test commit. Novel gaps (architectural decisions, geometry math, multi-line tactical logic) → STOP and report.
- **SDK script runs unmodified.** Anything that crashes is fixed engine-side, never by patching `sdk/`.
- **Test isolation autouse fixtures** clear `g_kSetManager._sets` + `g_kEventManager._method_handlers`. Do NOT clear `_broadcast_handlers` — KeyboardBinding's import-time registrations live there and downstream tests depend on them.

## Testing strategy

11 tasks following Slice B's task shape:

1. **`AddWeaponSystem` + `GetWeapons` + `RemoveAllWeaponSystems`** — unit test for basic state plumbing on the FireScript instance.
2. **Weapon-system casts** — `PhaserSystem_Cast`, `TorpedoSystem_Cast`, `TractorBeamSystem_Cast`, `ShipSubsystem_Cast` unit tests.
3. **Phaser power + torpedo ammo accessors** — `SetPowerLevel`, `PP_LOW`/`PP_HIGH`, `GetNumAmmoTypes`, `GetCurrentAmmoType` unit tests.
4. **`TorpedoTube.FireDumb` + `CalculateRoughDirection` + `WeaponSystem.StopFiringAtTarget`** unit tests.
5. **ai_driver first-tick FireScript CodeAISet analog** — unit test confirms `pEventHandler` and the broadcast handler get wired exactly once. Duck-typed gate distinguishes FireScript from SelectTarget (test both: FireScript-shaped instance gets wired, SelectTarget-shaped instance does not get the FireScript-specific wiring).
6. **`FireScript.Update` happy-path unit test** — 4 ticks under default config. Asserts the `iLastUpdate` cycle visits visibility-check, subsystem-pick, fire-A, fire-B in order. Expect this task to surface a handful of engine gaps — each becomes its own focused commit before the test commit.
7. **`ConfigureWeaponSystem` per-weapon-type tests** — phaser gets `SetPowerLevel(PP_LOW)` by default; torpedo gets `ChooseTorpType` called when `bChooseTorpsWisely=1`; non-matching weapon returns 1.
8. **`ChooseTargetSubsystem` basic rating test** — 3 subsystems with different shields/positions; assert the highest-rated subsystem ID gets cached on `inst.idTargetedSubsystem`. Skip `WeaponTooDangerous` / `CheckGoodShot` (out of scope).
9. **Integration test (minimal wiring)** — `tests/integration/test_fire_script_minimal.py`. Ship with phaser + torpedo, SelectTarget + FireScript wired on the same ship, target at distance 100. Tick 4 times. Asserts: target's hull condition decreased AND `ET_WEAPON_HIT` events fired with source=our-ship, destination=target.
10. **Integration test (real Compound, xfail)** — `tests/integration/test_non_fed_attack_smoke.py`. Load `AI.Compound.NonFedAttack.CreateAI(ship)`, tick once. `@pytest.mark.xfail(reason="awaits Slice D sub-graphs and Slice E Compound assembly")` enumerating the specific missing pieces. Documents the forward gap.
11. **Update deferred AI-runtime doc** — close Slice C bullet, refresh D/E status.

## Out of scope (deferred to D/E)

- `CheckGoodShot` heuristic (weapon arc + range + LOS) — stubbed to always True in Slice C.
- `WeaponTooDangerous` (overkill avoidance) — stubbed to always False.
- `PredictTargetLocation` (kinematic lead) — stubbed to current target position.
- Torp-type selection wisdom beyond stub (`bChooseTorpsWisely` path picks index 0 with ammo).
- Subsystem priority lists with full weighting tables.
- Tractor-beam mode logic.
- Hardpoint per-tube arc geometry.
- `OptimizedFireScript` C-backed replacement — never; we run the Python class.

These remain in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
