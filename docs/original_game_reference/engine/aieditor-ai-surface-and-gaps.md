# The AIEditor AI surface — what it reveals, and Dauntless's gaps against it

*Reverse-engineering reference. Source of truth: `sdk/Tools/AIEditor/` (the original BC
designer tool) and `sdk/Build/scripts/AI/` + `sdk/Build/scripts/Conditions/` (the runtime it
authors for). Cross-referenced against Dauntless's own AI runtime in `engine/appc/`.*

---

## 1. The central finding

**The AIEditor is a compile-time code generator, not a runtime.** `sdk/Tools/AIEditor/AIEditor.py`
(109 KB, Tkinter) lets a designer drag and connect AI nodes on a canvas and **saves the design
as Python**: a single `CreateAI(pShip)` function that wires up `App.<Type>AI_Create(...)`
primitives and returns the root node. It never executes any AI logic.

**Dauntless already runs that runtime.** [`engine/appc/ai.py`](../../../engine/appc/ai.py)
(1182 lines) reimplements every AI container type, and
[`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py) (477 lines) ticks the tree at
60 Hz inside [`engine/core/loop.py`](../../../engine/core/loop.py). `PlainAI.SetScriptModule()`
imports the **real SDK** `AI.PlainAI.*` / `AI.Compound.*` modules and instantiates them —
confirmed by `tests/unit/test_plain_ai_script_loading.py` (it loads `Stay.py` and runs its
`Update()`).

So the lesson is **not** "Dauntless must invent combat AI." The tactical logic lives in SDK
scripts Dauntless executes. What the AIEditor uniquely gives us is a **complete specification
of the AI surface** — every container type, every named preprocessor, and (through the runtime)
every Condition class the doctrines depend on. That converts the vague question "is our AI
done?" into a concrete, checkable coverage matrix. This document is that matrix.

### The output contract (why faithfulness is cheap)

Every file the editor saves has the same shape:

```python
import App
def CreateAI(pShip):
    pAttack = App.PlainAI_Create(pShip, "Attack")
    pAttack.SetScriptModule("AI.PlainAI.AttackRun")
    pAttack.SetInterruptable(1)
    pSeq = App.SequenceAI_Create(pShip, "MainSequence")
    pSeq.SetLoopCount(1)
    pSeq.AddAI(pAttack, 1)
    return pSeq
```

This is **exactly** the contract Dauntless's `ai.py` consumes (`PlainAI_Create`,
`SequenceAI_Create`, `SetScriptModule`, `AddAI`, …). **Any AI authored by the original editor
is loadable by Dauntless unchanged** — provided the primitives below are dispatched and the
Appc queries below resolve.

The editor ships its own runtime debugger too: `AIActiveLogView.py` + `socket.py` is a live
network-socket monitor for inspecting a running AI tree. Dauntless has no equivalent yet (see
Gap 5).

---

## 2. Layer A — AI container types (7)

The editor can emit 7 container types. Dauntless's dispatch lives in `ai_driver.py:tick_ai`
(the `isinstance` chain at lines 43–54) and the classes in `ai.py`.

| Container | Editor entity | Dauntless class | Dispatched? |
|---|---|---|---|
| `PlainAI` | `PlainAIEntity` | `ai.py:308` | ✅ `_tick_plain` |
| `SequenceAI` | `SequenceAIEntity` | `ai.py:419` | ✅ `_tick_sequence` |
| `PriorityListAI` | `PriorityListAIEntity` | `ai.py:391` | ✅ `_tick_priority_list` |
| `ConditionalAI` | `ConditionalAIEntity` | `ai.py:596` | ✅ `_tick_conditional` |
| `PreprocessingAI` | `PreprocessingAIEntity` | `ai.py:481` | ✅ `_tick_preprocessing` |
| `BuilderAI` (via `MakeBuilderAI.py`) | — | `ai.py:671` | ✅ `_tick_builder` |
| **`RandomAI`** | `RandomAIEntity` | `ai.py:459` | ❌ **no branch — falls through to `return ai._status`** |
| `CompoundAI` | `CompoundAIEntity` | n/a — emits a call to an `AI.Compound.*` module's `CreateAI`, which returns one of the above | n/a |

### Gap A1 — `RandomAI` is never ticked

`RandomAI` exists as a class with `AddAI` (`ai.py:459–476`) but `tick_ai` has **no
`isinstance(ai, RandomAI)` branch**, so a `RandomAI` node falls through to `return ai._status`
and never picks or runs a child. Low blast radius today (its main use is QuickBattle's
"FlyPointlessly" idle fallback in `QuickBattle/QuickBattleAI.py`), but any authored AI that
relies on random behaviour selection is silently inert. A `_tick_random` that picks one child
per evaluation and ticks it closes this.

---

## 3. Layer B — the 8 named preprocessors

The editor hard-codes 8 preprocessor factories (`AIEditor.py:171–180, 263–355`). These are the
highest-signal checklist because each is a discrete engine capability a doctrine assumes.

| Preprocessor | Purpose | Dauntless status |
|---|---|---|
| **Fire Preprocess** | weapon firing (`FireScript`) | ✅ wired — `ai_driver.py:_ensure_fire_script_initialized` (line 364) |
| **Select Target** | target selection + damage tracking (`SelectTarget`) | ✅ wired — `ai_driver.py:_ensure_select_target_initialized` (line 312) |
| **Alert Level** | alert-state escalation | ✅ works — handled via the generic `GotFocus` path (`ai_driver.py:242`); `ShipClass.SetAlertLevel` implemented (`ships.py:474`, collapses the XO-menu layer) |
| **Avoid Obstacles** | collision avoidance | ⚠️ partial — [`collision_avoidance.py`](../../../engine/appc/collision_avoidance.py) (188 ln) referenced from `core/loop.py`; minimal vs. SDK |
| **Tractor Beam Docking** | docking-stage tractor | ⚠️ tractor weapon + VFX shipped (`TractorBeamSystem`, modes); the *docking-sequence* AI (`AI/Compound/DockWithStarbase.py`) is unverified end-to-end |
| **Cloaking** | stealth attack behaviour | ❌ **gated off** — `ShipClass.GetCloakingSubsystem` returns `None` by design (`ships.py:581`); SDK `FedAttack`/`NonFedAttack`/`CloakAttack` test this truthy, so the cloak branch is never taken |
| **Starbase Attack** | stationary-target doctrine | depends on Compound + the conditions below |
| **Felix Report / AI Status** | telemetry/logging | n/a (debug-only) |

The `GotFocus`-vs-`Update` distinction matters: the driver already routes `AlertLevel`,
`CloakShip`, `Defensive`, etc. through `GotFocus` (see the comment at `ai_driver.py:242`), which
is why Alert Level works without special-casing.

---

## 4. Layer C — the 34 Condition classes (the silent-degradation surface)

`ConditionalAI` is only as capable as the `ConditionScript`s wired into it. Dauntless loads the
real `Conditions/*.py` via `ConditionScript` in `ai.py`, but **each condition calls Appc query
methods that must resolve** — and the failure mode is invisible: a missing query raises or
returns a default, the condition reads `False`, the guarded branch is never taken, and **no
error surfaces**. The Compound doctrines (`FedAttack` is 70 KB of conditional branches) degrade
silently rather than crash.

The table below is a **first-pass audit**: for each condition, the distinctive engine
method(s) it calls and whether a definition of that name exists anywhere in the Dauntless tree
(`App.py` + `engine/`). **Caveat:** a "missing" grep is a *flag to investigate*, not proof of a
bug — the method may be inherited via a base `ObjectClass`/`__getattr__`, provided in native
bindings, or only ever called on an SDK-internal helper object the condition constructs itself.
Re-run the audit method (below the table) before acting on any row.

| Condition | Key Appc calls | First-pass status |
|---|---|---|
| `ConditionInRange` | `GetClonedModelRadius`, `HasClonedModel`, `GetRadius`, `GetProximityCheck`, `GetWarpState` | ⚠️ `GetClonedModelRadius`/`HasClonedModel` not found — has `GetRadius` fallback |
| `ConditionInPhaserFiringArc` | `GetPhaserSystem`, `GetChildSubsystem`, `GetNumChildSubsystems` | ✅ all present |
| `ConditionInLineOfSight` | `GetLineIntersectObjects`, `GetProximityManager`, `GetNextObject` | ✅ present (`planet.py`, `ai.py`) |
| `ConditionInNebula` | `IsObjectInNebula`, `GetClassObjectList` | ✅ present (`nebula.py`, `sets.py`) |
| `ConditionIncomingTorps` | `GetClassObjectList`, `GetInternalInstance` | ✅ present |
| `ConditionTorpsReady` | `GetTorpedoSystem`, `GetNumReady`, `GetTorpedoTubes` | ⚠️ `GetTorpedoTubes` not found (`GetNumReady` present) |
| `ConditionPulseReady` | `GetPulseWeaponSystem`, `GetChargeLevel`, `GetMaxCharge`, `GetMinFiringCharge`, `GetChargeWatcher` | ⚠️ `GetChargeWatcher` not found (charge getters present) |
| `ConditionPowerBelow` | `GetMainBatteryWatcher`, `GetBackupBatteryWatcher`, `GetMainBatteryPower`, `GetMainBatteryLimit` | ⚠️ `*BatteryWatcher` not found — verify watcher vs. direct read |
| `ConditionSingleShieldBelow` | `GetShieldWatcher`, `GetShields`, `GetWatchedVariable` | ⚠️ `GetShieldWatcher` not found |
| `ConditionSystemBelow` | `GetConditionWatcher`, `GetNextSubsystemMatch`, `GetWatchedVariable` | ✅ `GetConditionWatcher`/`GetNextSubsystemMatch` present |
| `ConditionCriticalSystemBelow` | `GetSubsystems`, `IsCritical` | ✅ present |
| `ConditionSystemDisabled` / `ConditionSystemDestroyed` | `GetChildSubsystem`, `GetNextSubsystemMatch`, `IsDisabled`, `GetRoot` | ✅ present |
| `ConditionFiringTractorBeam` | `GetTractorBeamSystem`, `IsFiring` | ✅ present |
| `ConditionUsingWeapon` | `IsTypeOf` | ✅ present |
| `ConditionFacingToward` | `GetWorldLocation`, `GetWorldRotation`, `GetObjectsIfSameSet` | ✅ present (inherited geometry) |
| `ConditionAttacked` / `ConditionAttackedBy` | `GetFiringObject`, `IsHullHit`, `GetDamage`, `GetShields`, `GetHull` | ⚠️ `IsHullHit` not found on the hit-event object |
| `ConditionWarpingToSet` | `GetWarpEngineSubsystem`, `GetWarpSequence` | ✅ present |
| `ConditionWarpingToMission` | `GetDestinationEpisode`, `GetDestinationMission` | ⚠️ `GetDestinationMission` not found — mission-warp path |
| `ConditionReachedWaypoint` | `GetPlacement` | ⚠️ `GetPlacement` not found |
| `ConditionPlayerOrbitting` | `GetAI`, `GetID`, `GetSource` | ✅ present |
| `ConditionExists` | `GetActiveObjectTuple`, `GetObjPtr`, `GetObjID` | ✅ present |
| `ConditionInSet` / `ConditionAllInSameSet` / `ConditionAnyInSameSet` | `GetContainingSet`, `GetObjPtr`, `GetSet` | ✅ present |
| `ConditionShipDisabled` / `ConditionDestroyed` | `GetStatus`, `GetDestination` | ✅ present |
| `ConditionTimer` | `GetGameTime` | ✅ present |
| `ConditionDifficultyAt` / `ConditionFlagSet` / `ConditionMissionEvent` | (no engine geometry — flag/event reads) | ✅ no engine dependency |
| `FriendliesInPlayerSetStronger` | `GetPlayerSet`, `GetEnemyGroup`, `GetFriendlyGroup`, `GetCurShields` | ⚠️ group/`GetCurShields` helpers — verify |

**Net:** the bulk of conditions resolve. The investigate-list (≈10 rows) clusters into:
*watcher accessors* (`GetChargeWatcher`, `GetShieldWatcher`, `*BatteryWatcher`) which may be
SDK-side convenience objects rather than Appc surface; *cloned-model radius*
(`GetClonedModelRadius`/`HasClonedModel`) which has a `GetRadius` fallback; *hit-event*
(`IsHullHit`); and *mission/waypoint warp* (`GetDestinationMission`, `GetPlacement`). These are
the rows worth confirming before trusting `FedAttack`/`NonFedAttack` to brake at the right
ranges, manage power, and react to incoming fire faithfully.

---

## 5. The behaviour taxonomy the editor organizes

What the editor's blocks compose at runtime (the actual logic lives in `sdk/Build/scripts/AI/`):

- **PlainAI atoms** — movement: `Intercept`, `Flee`, `CircleObject` / `IntelligentCircleObject`,
  `MoveToObjectSide`, `FollowObject`, `FollowWaypoints`, `TurnToOrientation`, `ManeuverLoop`,
  `Stay`, `GoForward`; attack: `PhaserSweep`, `TorpedoRun`, `EvadeTorps`, `Ram`,
  `StationaryAttack`, `StarbaseAttack`; special: `Warp`, `TriggerEvent`, `RunScript`.
- **Compound doctrines** — `FedAttack` (70 KB), `NonFedAttack` (47 KB), `CloakAttack` (35 KB),
  `CallDamageAI` (damage response), `DockWithStarbase`; faction dispatch via
  `BasicAttack.CreateAI` on `pShip.GetShipProperty().GetSpecies()`.
- **Fleet AI** — `DestroyTarget`, `DefendTarget`, `DisableTarget`, `HelpMe`, `DockStarbase`.
- **Difficulty model** — `BasicAttack.g_lFlagThresholds`, a 0.0–1.0 scalar that unlocks
  capabilities as it rises: inaccurate torps → side arcs → power management → smart shields +
  subsystem targeting → smart torpedo selection → aggressive pulse. Verify
  `ConditionDifficultyAt` + the difficulty-flag plumbing carry through Dauntless so NPC
  difficulty actually scales.

---

## 6. Prioritized gap list

Ordered by leverage.

1. **Condition-class coverage audit (highest leverage).** Silent degradation makes doctrine
   faithfulness invisible. Turn §4's first-pass table into a confirmed pass/fail by running the
   audit method below and resolving the ~10 flagged rows. This is the single biggest
   faithfulness lever and is pure verification (no behaviour change for the ✅ rows).
2. **`RandomAI` dispatch (Gap A1).** Add a `_tick_random` branch to `tick_ai`. Small, isolated,
   removes a whole inert container type.
3. **`Avoid Obstacles` / collision-avoidance.** Currently partial; the Compound doctrines assume
   ships don't fly through each other / terrain. Compare `collision_avoidance.py` against the
   SDK preprocessor.
4. **`Cloaking` / `CloakAttack`.** `GetCloakingSubsystem` is a deliberate `None` stub; implement
   the cloak subsystem surface to unlock the cloak doctrines (Romulan/Klingon faithfulness).
5. **AI inspector (dev tool).** `AIActiveLogView.py` shows the original game shipped a live
   AI-tree monitor. A Dauntless developer-mode "AI inspector" overlay (render each ship's active
   AI subtree + current node + condition states) fits the existing dev tooling (Ship Property
   Viewer, Developer Options) and would make every gap above *observable* instead of inferred.
   Recommended as its own follow-up spec.
6. **Re-bornable editor (long horizon).** Because the editor's only output is `CreateAI(pShip)`
   Python that Dauntless already runs, a CEF-based visual AI editor is low-risk — it writes the
   same contract. Note as an option, not near-term.

---

## 7. Appendix

### How the §4 audit was generated (reproduce / extend)

For each `sdk/Build/scripts/Conditions/*.py`, extract its `.GetX(` / `.IsX(` / `.HasX(` call
footprint, then grep the Dauntless tree (`App.py` + `engine/`) for a definition of each name:

```sh
# footprint of one condition
grep -oE '\.(Get|Is|Has|Are)[A-Za-z]+\(' sdk/Build/scripts/Conditions/ConditionInRange.py | sort -u
# does Dauntless define it?
grep -rln "def GetClonedModelRadius(\|\"GetClonedModelRadius\"" App.py engine/
```

A miss is a *flag to investigate* (could be inherited / native / SDK-internal), not a proven
gap — confirm on the actual object the condition calls it on.

### File-path index

- **Editor:** `sdk/Tools/AIEditor/AIEditor.py` (entry), `ActionEntities.py`, `MakeBuilderAI.py`,
  `AIActiveLogView.py` + `socket.py` (live monitor).
- **Dauntless runtime:** [`engine/appc/ai.py`](../../../engine/appc/ai.py),
  [`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py),
  [`engine/appc/ship_motion.py`](../../../engine/appc/ship_motion.py),
  [`engine/appc/ships.py`](../../../engine/appc/ships.py),
  [`engine/appc/collision_avoidance.py`](../../../engine/appc/collision_avoidance.py),
  [`engine/appc/sensor_detection.py`](../../../engine/appc/sensor_detection.py),
  [`engine/core/loop.py`](../../../engine/core/loop.py).
- **SDK runtime authored by the editor:** `sdk/Build/scripts/AI/` (`PlainAI/`, `Compound/`,
  `Fleet/`, `Player/`, `Preprocessors.py`), `sdk/Build/scripts/Conditions/` (34 classes).
