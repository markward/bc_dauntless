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
| `RandomAI` | `RandomAIEntity` | `ai.py:459` | ✅ `_tick_random` (`ai_driver.py:478`) |
| `CompoundAI` | `CompoundAIEntity` | n/a — emits a call to an `AI.Compound.*` module's `CreateAI`, which returns one of the above | n/a |

**Every container type is now dispatched.**

### Gap A1 — `RandomAI` is never ticked — ✅ CLOSED 2026-06-29 (`f631cf31`)

_Was: `RandomAI` had the class and `AddAI` but `tick_ai` had no
`isinstance(ai, RandomAI)` branch, so the node fell through to `return ai._status` and never
picked or ran a child._

`_tick_random` (`ai_driver.py:478`) closes it, rather than the "pick one per evaluation" sketch
this section originally proposed: the node keeps a per-child *already-tried* array and draws
from the **un-tried** entries, clearing the flags and re-drawing when a child reports
DORMANT/DONE. Drawing with replacement would let the same evasive maneuver repeat back-to-back.
The node stays `US_ACTIVE` while a child runs, because its real use is as an infinite maneuver
picker inside a forever-looping `SequenceAI` (`AI/Compound/Parts/NoSensorsEvasive.py:47-52`,
`QuickBattle/QuickBattleAI.py:51-58`).

⚠️ **Citation corrected 2026-08-11 — separate the storage from the rule.** This paragraph used
to cite `RandomAI::Update` (`0x004917f0`) as RE'd ground truth for the already-tried array.
Checked against the clean-room reference, that overstates what is established:

- **Corroborated:** `RandomAI` is "a child array plus a parallel per-child weight/scratch array
  used to pick the next child" (`sizeof 0x40`, vtable `0x0088C1DC`), and the `+0x2c` array is
  **one byte per child** — allocated `count` bytes, *not* `count*4`. A byte-per-child array is
  the shape of a flag array, not of float weights, so our storage assumption holds up.
- **NOT established:** the selection rule itself. The reference states the run-tick and focus
  virtuals — `0x491620` / `0x491690` / `0x491740` / **`0x4917f0`** — are **SEH-framed walls**
  with no reconstructed body. So draw-without-replacement is *our inference from the storage
  shape and the SDK call sites*, not a recovered rule.

The behaviour is a reasonable reconstruction and the tests below pin it; just don't re-cite
`0x004917f0` as if its body had been read.

⚠️ **This section sat stale for five weeks and misled a later session into planning work that
was already done.** When closing a gap here, edit this file in the same change.

Covered end-to-end by `tests/integration/test_no_sensors_evasive_smoke.py::
test_losing_sensors_makes_the_ship_actually_jink`, which drives sensors across the disabled
threshold and asserts the ship accumulates real angular travel — measured 3.68 rad over 20 s,
and exactly 0.0 with the dispatch branch mutated out. The two older tests in that file assert
only tree SHAPE and "one tick doesn't raise" on a ship with no impulse engine, so an entirely
inert evasive passed both; that blind spot is how this gap and the `TurnTowardDifference`
no-op both survived.

### Observation — a one-shot subsystem kill skips the DISABLED event

Not a gap with a confirmed BC answer, recorded while testing the above.
`ShipSubsystem._condition_changed` fires `ET_SUBSYSTEM_DISABLED` only on the
`OPERATIONAL → DISABLED` transition; a condition slammed straight to 0 goes
`OPERATIONAL → DESTROYED` and fires `ET_SUBSYSTEM_DESTROYED` alone.
`Conditions/ConditionSystemDisabled` registers for `ET_SUBSYSTEM_DISABLED` /
`_OPERATIONAL` only, so a subsystem destroyed in a single hit never raises the
"system disabled" doctrines. Incremental combat damage crosses the disabled line on the way
down, so the doctrines do fire in ordinary play — which is why this is filed as an observation,
not a bug. Resolving it needs evidence on whether BC emits both events (or whether the
condition also watched DESTROYED).

**Asked of the clean-room reference 2026-08-11 — still open, and open for a specific reason.**
The query returned `below-relevance-floor` (best section `spec/ShipSubsystem.md § 1. Overview`
at 0.29, under the 0.35 floor). That is **retrieval-limited, NOT corpus silence** — do not
promote it to a documented gap. What the corpus *does* confirm is that the mechanism exists to
answer it: `ShipSubsystem` (`sizeof 0x88`, vtable `0x00892FC4`, class ID `0x801B`) holds "a pair
of **range-watchers** that fire callbacks as condition crosses thresholds", with the disable
threshold living on the companion `ShipSubsystemProperty`. So the disabled/destroyed edges are
threshold crossings on a watcher, and whether a single step across both thresholds fires one
callback or two is a property of that watcher. Retry against `FloatRangeWatcher` range-check
semantics (`AddRangeCheck` `0x005fb820`), not against event names.

Also worth noting for anyone writing tests against it: `ConditionSystemDisabled` is purely
event-driven. `SubsystemInfo.IsDisabled()` reads a cached `bDisabled` flag that starts at 0 and
is only raised by the event handler, and the initial `CheckRootState()` reads that same cold
flag — so a subsystem already disabled *before* the condition existed reads as healthy forever.
That is the SDK's own behaviour.

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
| **Cloaking** | stealth attack behaviour | ✅ **implemented** — `ShipClass.GetCloakingSubsystem` returns the real subsystem (`ships.py:992`); returns `None` only for hulls with no `CloakingSubsystemProperty`, which is the faithful behaviour. Corrected 2026-08-09 — see note below |
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

The table below was a **first-pass audit**: for each condition, the distinctive engine
method(s) it calls and whether a definition of that name exists anywhere in the Dauntless tree
(`App.py` + `engine/`).

> ### ⚠️ Resolved 2026-08-11 — every ⚠️ row below was an artifact of the audit method
>
> The ~10 flagged rows were **not** evidence of missing engine surface. The appendix's grep
> looks for `def <Name>(`, but SWIG binds most of the surface at **module level** instead:
>
> ```python
> DamageableObject.GetClonedModelRadius = new.instancemethod(Appc.DamageableObject_GetClonedModelRadius, None, DamageableObject)
> ```
>
> No `def`, so the grep could never match — and the receiver class it reports is wrong too
> (`GetClonedModelRadius` is on `DamageableObject`, not `ShipClass`). **All ten flagged names
> exist in the real published API**, confirmed against the clean-room reference's dispatch
> table (3,990 entries, graded *faithful* — name and address are identity facts):
>
> | Name | Real receiver | Original address |
> |---|---|---|
> | `GetClonedModelRadius` | `DamageableObject` | `0x006086f0` |
> | `HasClonedModel` | `DamageableObject` | `0x00608780` |
> | `GetShieldWatcher` | `ShieldClass` | `0x00616fe0` |
> | `GetMainBatteryWatcher` | `PowerSubsystem` | `0x0060f5f0` |
> | `GetBackupBatteryWatcher` | `PowerSubsystem` | `0x0060f660` |
> | `GetChargeWatcher` | `EnergyWeapon` (**not** `PulseWeaponSystem`) | `0x00617fb0` |
> | `IsHullHit` | `WeaponHitEvent` | `0x00616410` |
> | `GetPlacement` | `WaypointEvent` | `0x006062f0` |
> | `GetDestinationMission` | `WarpSequence` | `0x0061f7a0` |
> | `GetCurShields` | `ShieldClass` | `0x006171e0` |
>
> The watcher accessors are **real Appc surface, not SDK convenience objects** — that was the
> open question, and it is now closed. `FloatRangeWatcher_{GetWatchedVariable,AddRangeCheck,
> RemoveRangeCheck}` back them (`0x005fb7b0` / `0x005fb820` / `0x005fb8d0`), and Dauntless
> implements all three.
>
> `GetTorpedoTubes` was never engine surface at all: `ConditionTorpsReady.py:83` calls
> `self.GetTorpedoTubes(pShip)` — the condition's own method.
>
> **Caveat on absence.** The reference grades *presence* as an identity fact, but the contract
> is "95.3% covered and 87.0% named", so a name-based miss is **not** proof a call is absent.
> Only the ✅ direction above is settled.

| Condition | Key Appc calls | First-pass status |
|---|---|---|
| `ConditionInRange` | `GetClonedModelRadius`, `HasClonedModel`, `GetRadius`, `GetProximityCheck`, `GetWarpState` | ✅ API real (`DamageableObject`); Dauntless implements both |
| `ConditionInPhaserFiringArc` | `GetPhaserSystem`, `GetChildSubsystem`, `GetNumChildSubsystems` | ✅ all present |
| `ConditionInLineOfSight` | `GetLineIntersectObjects`, `GetProximityManager`, `GetNextObject` | ✅ present (`planet.py`, `ai.py`) |
| `ConditionInNebula` | `IsObjectInNebula`, `GetClassObjectList` | ✅ present (`nebula.py`, `sets.py`) |
| `ConditionIncomingTorps` | `GetClassObjectList`, `GetInternalInstance` | ✅ present |
| `ConditionTorpsReady` | `GetTorpedoSystem`, `GetNumReady`, `GetTorpedoTubes` | ✅ `GetTorpedoTubes` is the condition's own method, not engine surface |
| `ConditionPulseReady` | `GetPulseWeaponSystem`, `GetChargeLevel`, `GetMaxCharge`, `GetMinFiringCharge`, `GetChargeWatcher` | ✅ API real (`EnergyWeapon`); Dauntless implements it |
| `ConditionPowerBelow` | `GetMainBatteryWatcher`, `GetBackupBatteryWatcher`, `GetMainBatteryPower`, `GetMainBatteryLimit` | ✅ API real (`PowerSubsystem`); Dauntless implements both |
| `ConditionSingleShieldBelow` | `GetShieldWatcher`, `GetShields`, `GetWatchedVariable` | ✅ API real (`ShieldClass`, takes a facing index); Dauntless implements it |
| `ConditionSystemBelow` | `GetConditionWatcher`, `GetNextSubsystemMatch`, `GetWatchedVariable` | ✅ `GetConditionWatcher`/`GetNextSubsystemMatch` present |
| `ConditionCriticalSystemBelow` | `GetSubsystems`, `IsCritical` | ✅ present |
| `ConditionSystemDisabled` / `ConditionSystemDestroyed` | `GetChildSubsystem`, `GetNextSubsystemMatch`, `IsDisabled`, `GetRoot` | ✅ present |
| `ConditionFiringTractorBeam` | `GetTractorBeamSystem`, `IsFiring` | ✅ present |
| `ConditionUsingWeapon` | `IsTypeOf` | ✅ present |
| `ConditionFacingToward` | `GetWorldLocation`, `GetWorldRotation`, `GetObjectsIfSameSet` | ✅ present (inherited geometry) |
| `ConditionAttacked` / `ConditionAttackedBy` | `GetFiringObject`, `IsHullHit`, `GetDamage`, `GetShields`, `GetHull` | ✅ API real (`WeaponHitEvent`); Dauntless implements it |
| `ConditionWarpingToSet` | `GetWarpEngineSubsystem`, `GetWarpSequence` | ✅ present |
| `ConditionWarpingToMission` | `GetDestinationEpisode`, `GetDestinationMission` | ❌ **REAL GAP** — API real (`WarpSequence`), absent in Dauntless; live-stubbed |
| `ConditionReachedWaypoint` | `GetPlacement` | ❌ **REAL GAP** — API real (`WaypointEvent`), absent in Dauntless; live-stubbed |
| `ConditionPlayerOrbitting` | `GetAI`, `GetID`, `GetSource` | ✅ present |
| `ConditionExists` | `GetActiveObjectTuple`, `GetObjPtr`, `GetObjID` | ✅ present |
| `ConditionInSet` / `ConditionAllInSameSet` / `ConditionAnyInSameSet` | `GetContainingSet`, `GetObjPtr`, `GetSet` | ✅ present |
| `ConditionShipDisabled` / `ConditionDestroyed` | `GetStatus`, `GetDestination` | ✅ present |
| `ConditionTimer` | `GetGameTime` | ✅ present |
| `ConditionDifficultyAt` / `ConditionFlagSet` / `ConditionMissionEvent` | (no engine geometry — flag/event reads) | ✅ no engine dependency |
| `FriendliesInPlayerSetStronger` | `GetPlayerSet`, `GetEnemyGroup`, `GetFriendlyGroup`, `GetCurShields` | ✅ `ShieldClass_GetCurShields` real; group helpers are SDK-side |

**Net (resolved 2026-08-11):** the ≈10-row investigate-list collapsed to **two real gaps**.
Eight rows were audit-method artifacts — the surface is real *and* Dauntless already implements
it, so `FedAttack`/`NonFedAttack` brake, manage power, and react to incoming fire against live
watchers rather than degrading silently. What remains:

### Gap C1 — the waypoint-arrival event does not exist — ✅ FIXED 2026-08-11

`ET_AI_REACHED_WAYPOINT` and `WaypointEvent` are **both absent** from `App.py` and `engine/`.
The emitter is SDK script, not engine: `AI/PlainAI/FollowWaypoints.py:280` does
`App.WaypointEvent_Create()` → `SetPlacement(...)` → `SetEventType(App.ET_AI_REACHED_WAYPOINT)`
and broadcasts. With the class undefined the event object is a `_NamedStub`, and with the
constant undefined it collapses to `int() == 0` — the exact class CLAUDE.md says to treat as a
live bug rather than noise.

**This is not speculative — it is live-measured.** `docs/stub_heatmap.md` ranks it:

| Rank | Owner | Attr | Hits | Runs |
|---|---|---|---|---|
| 108 | `App` | `ET_AI_REACHED_WAYPOINT` | 90 | 31/233 |
| 109 | `App` | `WaypointEvent_Create` | 90 | 31/233 |
| 113 | `WaypointEvent_Create()` | `SetPlacement` | 90 | 31/233 |
| 76 | `WaypointEvent_Create()` | `GetEventType` | 180 | 31/233 |

Consumers that therefore never fire: `Conditions/ConditionReachedWaypoint` (registered by
`AI/Setup.py:125`) and the mission handler at
`Maelstrom/Episode8/E8M2/E8M2.py:514`. Any doctrine or mission beat gated on "ship reached its
waypoint" is dead.

**Fixed:** `WaypointEvent` (+ `WaypointEvent_Create`) in `engine/appc/events.py` — it subclasses
`TGEvent`, so only `Get/SetPlacement` is new; everything else was inherited. Constant
`ET_AI_REACHED_WAYPOINT = 210` in `App.py`, contiguous with the 200–209 AI/condition block.
Python only, no native change. Covered by
`tests/integration/test_follow_waypoints_reached_event.py` (5 tests): the real SDK producer
flies a real `App.Waypoint`, and the real SDK `ConditionReachedWaypoint` goes 0 → 1 with no test
double in between. Each was watched failing first; the negative test (arrival for a *different*
waypoint must not fire) was separately proven sensitive by pointing it at `WP1`.

### Gap C2 — `WarpSequence.GetDestinationMission` is missing, and it fails *true* — ✅ FIXED 2026-08-11

`GetDestinationMission` (`0x0061f7a0`) and `GetDestinationEpisode` (`0x0061f810`) are both
absent from our tree. `ConditionWarpingToMission.py:23` reads:

```python
if pWarpSequence and (pWarpSequence.GetDestinationMission() or pWarpSequence.GetDestinationEpisode()):
    self.pCodeCondition.SetStatus(1)
```

A missing attribute resolves to a **truthy** `_Stub`, so this condition reports **"warping to a
new mission" for every warp sequence that exists** — an inverted failure, not a silent-off one.
Live-confirmed at heatmap rank 95 (`WarpSequence_Cast()` → `GetDestinationMission`, 136 hits,
58/233 runs). Consumer: `AI/Compound/FollowThroughWarp.py`, registered by `AI/Setup.py:135`.

**It was three missing names, not one — and the third was the worst.** Writing the baseline test
("a ship that is not warping at all must read false") exposed that **`WarpSequence_Cast` was also
undefined** — heatmap **rank 62, 326→286 hits, the highest-traffic name in this gap**, and it had
been sitting in the table above the row that prompted the investigation. Both
`ConditionWarpingToSet.CheckState` and `.SequenceSet` wrap `GetWarpSequence()` in that cast and
then branch on `if pWarpSequence`, so a truthy `_Stub` meant a ship with **no warp sequence at
all** still tested as warping. The accessor fix alone would have left the condition wrong in the
commonest case of all.

**Fixed:** `WarpSequence_Cast` plus `GetDestinationMission`/`GetDestinationEpisode` (backed by
`_dest_mission`/`_dest_episode`, both `None`) in `engine/appc/warp.py`. Returning falsy is the
*correct* answer, not a placeholder: `WarpSequence_Create` only ever carries a **set**
destination and nothing in the tree calls `SetEventDestination`, so Dauntless constructs no
cross-mission warp today. When one is built, store the target in those fields rather than
reintroducing the stub. Covered by `tests/unit/test_condition_warping_to_mission.py` (3 tests).

#### Residual — `ET_SET_WARP_SEQUENCE` is still undefined (NOT fixed here)

Surfaced by the same tests via a stub-hardening warning. `ConditionWarpingToSet.__init__`
registers a `SequenceSet` handler on it (heatmap **ranks 58/59, 326 hits, 75/233 runs**), which
is how the condition is meant to re-evaluate when a warp *starts after* the condition was
created. Undefined, it collapses to `int() == 0`, so today the condition only ever evaluates
once — at construction, via `CheckState()`. The fixes above make that one evaluation **correct**;
they do not make it **timely**. Closing this needs a real constant *and* an emitter at
`WarpEngineSubsystem.SetWarpSequence`, which is a behaviour change to the warp path and belongs
in its own change with its own live pass.

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

### Confirmed against the clean-room reference, 2026-08-11 — no gap, recorded so it is not re-opened

**The fuzzy evaluator is a Layer-B dependency this document never listed, and we are covered.**
`spec/ConditionalAI.md` establishes that `FuzzyLogic` is BC's *other* scripted decision
mechanism and is **not reached from a ConditionalAI** — that path "touches nothing but its own
table, and the truth-table builder passes its callable nothing but booleans." Where it *is*
used, by census: 14 `BreakIntoSets` call sites across exactly **seven files, all under the AI
script tree** — six leaf behaviours (`CircleObject`, `Flee`, `FollowObject`, `FollowWaypoints`,
`Ram`, `TorpedoRun`) plus `AI/Preprocessors.py`, which holds 4 of the 14. Our own SDK grep
returns those same seven files, and Dauntless implements both `FuzzyLogic_BreakIntoSets` and
the `FuzzyLogic` weighted-edge rule engine (`App.py:621`, `:660`). So six of the movement atoms
in §5 depend on it and it is present — but note the reference grades that section
*reviewed-not-tested*, and it explicitly **refuses** the symmetric claim that a fuzzy score
decides a condition's flag (falsifier: a condition script that grades a reading through the
fuzzy evaluator — none exists in the corpus).

**`PriorityListAI`'s DONE latch is confirmed, at the corpus's highest grade.**
`spec/PriorityListAI.md § 1` is graded **faithful** ("every offset, every constant and every
branch is read from the original image") and states it directly: *"a child that reports itself
`Done` is switched off permanently … A child that reports itself `Dormant` is not switched off
— it is simply passed over on that tick and tried again on the next one. So `Done` is a latch
and `Dormant` is a pause."* That is independent confirmation of the dormant-child-recovery fix
already shipped in `_tick_priority_list`. Children are `0xC`-byte priority entries, object
`sizeof 0x38`, dispatch table `0x0088C188` (21 entries), constructed script-side through
`PriorityListAI_Create` (`0x00604560`).

**The four AI state virtuals are named correctly in our tree.** The reference renamed these on
2026-08-10 from its earlier `Activate`/`Deactivate`/`AcquireFocus`/`ReleaseFocus` to the
program's own names — `SetActive` / `SetInactive` / `GotFocus` / `LostFocus`
(`0x00470700`–`0x00470730`, **byte-exact**; each just sets or clears the `active` `+0x20` or
`hasFocus` `+0x21` byte, no return). `engine/appc/ai.py` and the `GotFocus` routing at
`ai_driver.py:242` already use those names, so §3's Alert Level row rests on the right seam.

---

## 6. Prioritized gap list

Ordered by leverage.

1. ~~**Condition-class coverage audit (highest leverage).**~~ ✅ **DONE 2026-08-11.** All ~10
   flagged rows resolved against the clean-room reference; 8 were audit-method artifacts. Two
   real, live-hit gaps fell out and inherit the priority:

   1a. ~~**Gap C2 — `WarpSequence.GetDestinationMission`.**~~ ✅ **DONE 2026-08-11** — and it was
   three names, not two: `WarpSequence_Cast` (rank 62) was missing too, which made the condition
   fire even for ships that were not warping.

   1b. ~~**Gap C1 — `WaypointEvent` + `ET_AI_REACHED_WAYPOINT`.**~~ ✅ **DONE 2026-08-11.**

   1c. **`ET_SET_WARP_SEQUENCE` (new, opened by 1a).** The warp conditions can only evaluate at
   construction until this constant exists and `SetWarpSequence` emits it. Ranks 58/59, 326 hits.
   See the residual note in §4.
2. ~~**`RandomAI` dispatch (Gap A1).**~~ ✅ **DONE 2026-06-29 (`f631cf31`)**, end-to-end test
   added 2026-08-06. See Gap A1 above.
3. **`Avoid Obstacles` / collision-avoidance.** Currently partial; the Compound doctrines assume
   ships don't fly through each other / terrain. Compare `collision_avoidance.py` against the
   SDK preprocessor.

   **Queried 2026-08-11 — the reference cannot close this one yet, and it says why.**
   "obstacle avoidance preprocessor" returns `below-relevance-floor` (best 0.26), and the
   spatial index behind it is explicitly unreconstructed: `ProximityManager_Update`
   (`0x005a83a0`) is catalogued **state: stub** — address established, body not. Neighbouring
   entries *are* byte-exact (`ProximityManager_{AddObject,RemoveObject}` `0x00614850` /
   `0x006148f0`, `SetClass_GetProximityManager` `0x005ef010`, `DumpCollisions` `0x005a8770`),
   and `spec/ProximityManager.md` documents "one spatial index, two populations, and a
   three-call query protocol" — so the *query surface* is recoverable even though the per-frame
   update is not. Note the reference's own routing caveat: it is "weak for floating-point
   computation and per-frame update paths, which are disproportionately untested clones" —
   exactly this shape of question. Treat avoidance steering as a designed approximation, like
   the tractor spring-damper, unless that section is later graded.
4. ~~**`Cloaking` / `CloakAttack`.** `GetCloakingSubsystem` is a deliberate `None` stub~~
   ✅ **WAS ALREADY DONE — this entry was wrong.** Corrected 2026-08-09.

   `GetCloakingSubsystem` returns the real subsystem (`engine/appc/ships.py:992`); the
   cloaking system shipped (phases A–E). This row was written before that work and never
   updated, and on 2026-08-09 it caused a *false confirmed gap*: the clean-room reference
   was asked to confirm `ShipClass_GetCloakingSubsystem` (it does exist, dispatching at
   `0x0060a4b0`), and the combination was reported as settling a design question and
   warranting implementation. It warranted nothing — the code had been there for months.

   **The lesson, not the line, is what matters here:** a prose gap-doc is *never* evidence
   about our own implementation. Read the code. This entire document is a map drawn at one
   moment; treat every ❌ in it as a hypothesis to re-check against `engine/`, not a fact.

   Remaining genuine cloak work is tracked elsewhere: Phase E VFX and decloak cadence.

   **Dead surface, deliberately absent.** `CloakingSubsystem_{Get,Set}CloakTime` and
   `CloakingSubsystem_{Get,Set}ShieldDelay` exist in the SWIG binding with **zero** call
   sites across the 1,228 SDK scripts, so they are not implemented and should not be
   rediscovered as a gap. Per the clean-room reference's object model for
   `CloakingSubsystem` (`sizeof` = `0xBC`), the backing values `g_cloakTime` (`0x8e4e1c`)
   and `g_shieldDelay` (`0x8e4e20`) are **class-static globals** — one shared cloak cadence
   across every ship, *not* per-instance fields. Build them that way if they are ever
   needed. (Layout section graded *partial*; rows marked scouted are unverified.)
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

> ⚠️ **The method below is the one that produced §4's ten false flags.** It is kept for the
> footprint step only. **Do not use a `def <Name>(` grep to decide whether engine surface
> exists** — read the corrected method that follows it.

For each `sdk/Build/scripts/Conditions/*.py`, extract its `.GetX(` / `.IsX(` / `.HasX(` call
footprint:

```sh
grep -oE '\.(Get|Is|Has|Are)[A-Za-z]+\(' sdk/Build/scripts/Conditions/ConditionInRange.py | sort -u
```

**Corrected method (2026-08-11).** Two fixes — resolve the receiver from the SWIG surface, and
grep loosely on our side:

```sh
# 1. WHICH CLASS does the method belong to? SWIG binds most of the surface at module
#    level, so `grep "def GetClonedModelRadius"` on sdk App.py returns NOTHING even
#    though the method exists. Grep the bare name instead — the binding line names the class:
grep -n "GetClonedModelRadius" sdk/Build/scripts/App.py
#   -> DamageableObject.GetClonedModelRadius = new.instancemethod(
#          Appc.DamageableObject_GetClonedModelRadius, None, DamageableObject)
#      ...so the receiver is DamageableObject, NOT ShipClass.

# 2. Does Dauntless implement it? Grep the bare name across the whole tree, not `def`:
grep -rn "GetClonedModelRadius" App.py engine/
```

Then confirm the name against the clean-room reference (`ask_reference`, `area="api"`) using
the **full `Class_Method` entry name** — a bare method name matches by prefix and returns a
20-row namespace dump instead of an answer. A hit there is graded *faithful* (name + address
are identity facts). A **miss is not proof of absence**: the contract is 95.3% covered and
87.0% named.

Finally, cross-check `docs/stub_heatmap.md` — it tells you whether a genuinely-missing name is
actually *hit at runtime*, which is what separates a live bug (Gaps C1/C2) from dead surface.

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
