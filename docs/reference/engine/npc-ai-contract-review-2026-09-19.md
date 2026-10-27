# NPC AI contract review — 2026-09-19

*Does Dauntless implement full support for the AI contract the SDK scripts
depend on? Audited at `09f2c960` (branch `feature/ship-bridge-matrix`).
Supersedes the coverage claims in `aieditor-ai-surface-and-gaps.md` §3–§4 and
`ai-system-review-2026-08-10.md` where they disagree; both remain useful for
the runtime-structure findings they record.*

## Verdict

**No — but the shortfall is narrow and almost entirely enumerable.**

- The **runtime structure** is complete: all 7 container types, all 102 SWIG
  bindings on the AI classes that any script calls, every `App.*` name that the
  `AI/` and `Conditions/` trees reference except **seven**, and every method
  name they call except **five**. 497 AI-related tests pass.
- The **behaviour layer** is not: five undefined engine names, two event
  families that are never emitted, one unreachable state attach, and one
  script path that raises out of the tick together break a specific and
  identifiable set of doctrines. Table in §2.
- Most of the fixes are one-function cast/helper additions. Two are real
  work (ObjectGroup membership events; player fire-control methods on
  `OptimizedFireScript`). One is a **policy decision** (script exceptions
  propagate out of `loop.tick()`; BC's C++ swallows them).

Coverage by layer, from the four slice audits:

| Layer | Items | FULL | PARTIAL | BROKEN | Unused in SDK |
|---|---|---|---|---|---|
| Containers + class surface | 7 types, 102 bindings | all | — | — | `LogAITree`, `ProximityCheck_GetObject` |
| Preprocessors (`AI/Preprocessors.py`) | 9 classes | 4 | 3 | 1 (`AvoidObstacles`, derived) | `ManagePower` body dead in BC |
| Leaf behaviours (`AI/PlainAI/`) | 26 | 17 | 2 | 5 | 2 |
| Compound / Fleet / Player / QuickBattle | 26 modules | 19 | 5 | 2 (Defend, HelpMe/DefendTarget) | — |
| Conditions (`Conditions/`) | 33 | 21 | 8 | 4 | 1 (`DifficultyAt`) |

## 1. Method

1. **Mechanical name audit.** Every `App.<Name>` token in `AI/**` and
   `Conditions/**` was resolved against our `App` module **rejecting
   `_NamedStub`** (a plain `hasattr` is always true here — the first pass of
   this audit was defeated by exactly that). Every `.Method(` token was
   bare-name grepped across `App.py engine/` (never `def <Name>(`, per
   CLAUDE.md), then filtered against names the SDK defines itself.
2. **Class-surface audit.** Every `Class.Method = new.instancemethod(...)`,
   `def Class_Fn(` and `Class_X = Appc.` line for the AI classes in the SDK
   `App.py` was checked the same way.
3. **Four slice audits** (subagents, read-only): Preprocessors, PlainAI,
   Compound/Fleet/Player/Setup/QuickBattle, Conditions + condition runtime.
   Each read bodies for placeholder returns, traced what a truthy stub /
   `int()==0` collapse does to the branch, and named real-class test coverage.
4. **Cross-checks** against `docs/stub_heatmap.md` (416 live runs to
   2026-08-31) and a headless probe for the top-ranked crash.

Scratch artefacts: `check_app_names.py`, `check_methods.py`,
`check_class_surface.py`, `probe_disable_order.py` in the session scratchpad.

## 2. Gaps, ranked by blast radius

Evidence tiers: **OBSERVED** = reproduced headless or live-measured in the
heatmap; **READ** = traced in code; **DERIVED** = arithmetic over stub
semantics, not yet observed.

| # | Gap | Evidence | What breaks | Fix shape | Status |
|---|---|---|---|---|---|
| 1 | `App.TGPoint3_GetRandomUnitVector` undefined | OBSERVED — heatmap rank 1–3/6/11–14, **80,805 hits** | `Flee` with ≥2 pursuers never turns (full speed on current heading, forever). `EvadeTorps` with ≥2 torps holds heading. `Warp` (125 SDK sites) with any obstacle in its forward 4000-GU capsule sits at speed 0 and retries forever. `AvoidObstacles` flee-direction scoring: 8 of 9 candidates are stubs and the stub wins in head-on geometry (DERIVED) | one function on `TGPoint3` | ✅ `e02c28b1` |
| 2 | `App.PhaserBank_Cast` undefined | OBSERVED — heatmap 7–10/61, 23,864 hits | `PhaserSweep` never brings side/rear arcs to bear. `ConditionInPhaserFiringArc` reads **TRUE forever** → FedAttack's `TorpsReadyAndNotInEnemyFiringArc` branch (`FedAttack.py:426`) permanently dormant | cast; class exists (`weapon_subsystems.py:2252`) | ✅ `8cb435f2` |
| 3 | `App.PulseWeaponProperty_Cast` undefined | OBSERVED — heatmap 83–88 | `ConditionPulseReady` reads **FALSE forever** → every NonFedAttack ship never takes its pulse-ready branch (`NonFedAttack.py:272,545`) | cast; class exists (`properties.py:627`) | ✅ `35d96199` (+ `d5c1930c`, `2e7f4078` shutdown guard) |
| 4 | `ET_OBJECT_GROUP_OBJECT_ENTERED_SET` / `_EXITED_SET` / `ET_OBJECT_GROUP_CHANGED` never emitted | READ — `ObjectGroup.SetEventFlag` stores the flag (`objects.py:1118`); zero producers in `engine/`+`App.py`; 13 SDK subscriber files, 21 `SetEventFlag` sites | `ConditionAllInSameSet` (25 mission AIs) and `AnyInSameSet` frozen at construction value; late-spawn re-arm dead in `Exists`, `FacingToward`, `InLineOfSight`, `InPhaserFiringArc`, `InRange`, `SystemBelow`, `CriticalSystemBelow`; `Preprocessors.SelectTarget` and `HelmMenuHandlers` also subscribe | membership-diff emitter on set add/remove (same shape as the `ET_TARGET_LIST_*` pair closed 2026-09-02). **Invisible to the heatmap** — constants are real | ✅ `d6cd43f5` — ENTERED_SET/EXITED_SET only; `ET_OBJECT_GROUP_CHANGED` still has no producer (scoped out; see §7 residuals) |
| 5 | `ET_DELETE_OBJECT_PUBLIC` never emitted | READ — only `constants_generated.py:345` and a docstring; 14 SDK subscriber files | `ConditionExists` never returns to 0 after its target dies (FollowThroughWarp/ChainFollow); `InNebula.ObjectDeleted`, `InRange.ProxDeleted` dead | emitter at object removal | ✅ `dff0cd05` (+ `1629b479` isolation) — `ConditionInRange.ProxDeleted` stays dead (see §7 residuals) |
| 6 | `FireScript.ChooseTargetSubsystem` → `self.GetChildTargets` (`Preprocessors.py:832`), defined nowhere in the SDK | **OBSERVED** — `probe_disable_order.py`: `AttributeError` out of `tick_ai` after ~0.8 s once the target subsystem is non-targetable | Every explicit-`TargetSubsystems` tree: `AI/Fleet/DisableTarget`, every `AI/Player/Disable*` order. Stock hardpoints mark Impulse/Warp/Phasers/Torpedoes/Tractors/Engineering `SetTargetable(0)` (`galaxy.py:774…995`), so the branch is the common case. **Dead in BC** (native FireScript) — live only for us. Nothing guards it: `_tick_preprocessing` → `tick_all_ai` → `loop.py:46` → `host_loop.py:8784` | implement `GetChildTargets` in the wrapper, or guard | ✅ `47d1e577` |
| 7 | `App.WeaponSystem_Cast` + `WeaponSystem.IsInTargetList` undefined | OBSERVED — heatmap 115/116/167 | `PlainAI/StarbaseAttack` never calls `StartFiring` → E7M3 starbases never shoot | cast + method | ✅ `1d251b85` |
| 8 | `WarpEngineSubsystem.SetWarpSequence` has **no caller** in production | READ — `subsystems.py:1491`; only tests call it; `WarpSequence_Create(...).Play()` (`warp.py:875`) does not | `ConditionWarpingToSet` reads FALSE forever (nine E5M4 Orbit/Patrol AIs). The `ET_SET_WARP_SEQUENCE` emitter closed 2026-09-02 is real but unreachable — the *post* was closed, the *state attach* never was | call it from the warp path | ✅ `18fc21b6` (+ `8b64a5bd`) |
| 9 | Script exceptions propagate out of the sim tick | READ — no `try` in `_tick_plain`/`_tick_preprocessing`/`tick_all_ai`/`loop.tick` | #6 above; `Defend.py:18 GetConditionScript` (SDK bug — not SWIG-bound in BC either; raises every 5 s once the defendee is attacked; `Fleet/HelpMe`, `Fleet/DefendTarget`); `FollowThroughWarp` cross-set path (`raise` of a str). BC's embedded Python reports and continues | policy: per-node guard + dev-mode print | ✅ `d6973a26` |
| 10 | `App.TGCondition_Cast` undefined | OBSERVED — heatmap 122/130 | `MissionLib.ConditionChangedRedirect:2536` passes a truthy stub as status on **both** edges (E7M6 `g_bInOrbit` never clears; E7M2/E8M1/E8M2 fire on the falling edge); E2M0 `PlayerInHelp` doubly inert because `TGCondition` is not a `TGObject` (`ai.py:47`) so `TGObject_GetTGObjectPtr` cannot find it | cast + make `TGCondition` id-registered | ✅ `4deec9ba` (+ `59def8c7` weak registration) |
| 11 | Player fire-control via `OptimizedFireScript` | READ — `App.OptimizedFireScript` is now a real class, so `isinstance` no longer raises (memory note is stale), but our `FireScript_NonLethal` is not a subclass of it → `g_lPlayerFireAIs` always empty | Tactical-menu "Manual Aim" (`SetEnabled(0)`), "Phasers only" (`RemoveAllWeaponSystems`), "Target at will" (`Ignore/RestoreSubsystemTargets`) are no-ops. The AI still fires; only the player's *control* of it is dead. The 7 `OptimizedFireScript.*` bindings are also unimplemented (Maelstrom E6/E7 AIs call `AddWeaponSystem` on the SDK instance, which works) | make the wrapper an `OptimizedFireScript` | ✅ `c4eb6a0e` (+ `e517aa86`) |
| 12 | `TGTimerManager.AddTimer` returns `None` (`timers.py:69`) | READ | `ConditionAttacked/AttackedBy` guard on `if AddTimer(...)` → forgiveness timers never recorded, never cancelled → conditions reach TRUE less often than BC (Defend + 19 AttackedBy consumers) | return the id | ✅ `b67afe3a` |
| 13 | `App.TGGeomUtils_LineSphereIntersection` undefined (class absent too) | READ, not in heatmap | `Intercept` obstacle refinement always passes → dodges the *first* candidate, not the nearest | one geometry helper | ✅ `b1fc871e` (+ `cf0fc780` tests) |
| 14 | `SelectTarget` native-era hooks not wired (`ObjectDecloaked`, `TargetEnteredSet`, `OurShipEnteredSet`, `TargetListChanged`) | READ — only comments at `ai.py:597`, `ai_driver.py:1232` | Re-acquisition waits for the 5 s cadence / dormant re-probe instead of the event | wire to `ET_DECLOAK_BEGINNING` / set events | ✅ `3b7d5860` — `ObjectDecloaked`/`TargetEnteredSet`/`OurShipEnteredSet` wired; `TargetListChanged` is NOT (depends on `ET_OBJECT_GROUP_CHANGED`, gap #4; see §7 residuals) |
| 15 | No `ClearAI` on ship death or set removal | READ — only `ships.py` touches the AI slot | A destroyed ship's tree gets no `LostFocus` / `ET_AI_DONE` (`Warp.LostFocus` re-enables collisions on a dead ship) | call from `ship_death` | ✅ `7800fcf4` |

Placeholders that are *not* bugs today but are the next thing a doctrine
will trip on: `PreprocessingAI.ForceDormantStatus`/`ForceStatusChange` are
`pass` (`ai.py:935`; `ChainFollowThroughWarp` uses them to un-dormant on a
follow-target change); `ShipSubsystem.GetCombinedConditionPercentage` has no
child aggregation (`subsystems.py:660`, comment stale); `IsHittableFromLocation`
returns `1.0`; `g_kSystemWrapper.GetTimeSinceFrameStart` returns `0.0`;
`ObjectClass.SetAcceleration` is `pass`; `HasBuildingAIs` is always `False`;
the `ManagePower` replacement performs no power management
(`ai_optimized.py:120`); `ConditionSingleShieldBelow` names its hook
`RegisterSetTarget`, so `AddCondition` never wires it; `ShieldSubsystem`-side
`ET_SUBSYSTEM_*` events are posted with destination = ship, so
`ConditionPulseReady`'s per-weapon registrations can never match.

Dead surface, deliberately absent, do not re-open: `LogAITree`,
`ProximityCheck_GetObject`, `ProximityManager.Update`,
`ProximityManager_{Get,Set*}PlayerCollisionsEnabled`,
`ProximityCheck_GetNumClassObjects`, `TGConditionAction`, `EvilShuttleDocking`,
`TriggerEvent`, `ConditionDifficultyAt` (zero SDK consumers).

## 3. What is confirmed working

- Species dispatch and difficulty: `GetSpecies()` real ints, `Game_GetDifficulty`
  real, `BasicAttack.SetFlagsFromDifficulty` pure SDK. Galaxy → FedAttack,
  Klingon → NonFedAttack, cloaked → CloakAttackWrapper (probed).
- Fleet override idiom (`HelmMenuHandlers.OverrideAIInternal`) re-parents a
  live BasicAttack under `FleetCommandOverrideAI` correctly (probed). **Zero
  tests import `AI.Fleet.*`.**
- Player orders install through `TacticalMenuHandlers.StartAI` →
  `MissionLib.SetPlayerAI`; `_PlayerControl` hands motion to the AI and
  cancels on manual input (`test_player_ai_motion_handoff.py`).
- QuickBattle's four AI modules resolve every primitive.
- 17 of 26 leaves FULL with real-class smoke tests; `ConditionUsingWeapon`,
  `TorpsReady`, `ReachedWaypoint`, `Timer`, `InRange`, `SystemBelow`,
  `PowerBelow` covered end-to-end with the real SDK class.
- `RegisterExternalFunctions` wiring (name → list) is current.

## 4. Why the tests did not catch this

Most PlainAI smoke tests assert **status only** ("one tick doesn't raise",
"returns ACTIVE") — `Flee`, `Warp`, `EvadeTorps`, `PhaserSweep`,
`StarbaseAttack` all pass with the behaviour entirely inert. None places an
obstacle in `Warp`'s capsule, none puts two pursuers behind `Flee`. The
`ConditionExists` transition tests post the group event **by hand**, which
proves the consumer and hides the missing producer. `test_fire_script_choose_subsystem.py:5`
explicitly skips the explicit-`TargetSubsystems` branch that #6 crashes in.
`test_no_sensors_evasive_smoke.py` is the model to copy: it asserts
accumulated angular travel and was proven sensitive by mutating the dispatch
out.

## 5. Stale claims found in other documents

- `aieditor-ai-surface-and-gaps.md` §3 cites `ai_driver._ensure_fire_script_initialized`
  (line 364) — deleted; `CodeAISet` is dispatched at bind (`ai.py:921`). §4's
  `WarpSequence_Cast` closure is real; its "34 conditions" is 33.
- `docs/stub_heatmap.md` rows 71/89/90 (`WarpSequence_Cast…`) and 91
  (`Torpedo_Cast().GetObjID`) are resolved but unmarked. Rows 22–26/32–33
  (`PhaserSystem.CanFire`, `GetAmmo`, `GetNumShields`, 2 runs) come from
  `engine/ui/ai_inspector_model.py`, not the SDK.
- `collision_avoidance.py` docstring (:19–30) describes a caller that no longer
  exists; `tick_collision_avoidance` is reached only by tests.
- Memory note `project_optimizedfirescript_stub_breaks_orders`: the
  `isinstance` crash is fixed; the residual is #11 above.
- `event-emitter-gaps.md` #12 (`ET_SET_WARP_SEQUENCE`): emitter is real, state
  attach never happens (#8).

## 6. Suggested order

1. #1, #2, #3, #7, #10, #13 — six missing names, all trivial, four of them
   top-heatmap. Write each test the way §4 says: assert the *behaviour*, then
   prove it fails with the name removed.
2. #6 + #9 together — the crash and the guard policy are one decision.
3. #4, #5 — the two un-emitted event families; both need a membership diff.
4. #8, #12, #11, #14, #15.

## 7. Execution notes (close-out, 2026-09-19)

- #6: `_TGTypedEvent.SetSource`/`GetSource` in `App.py` were silent stubs and
  were fixed — `MissionLib.ConditionChangedRedirect` needed them. Conditions
  register **weakly** in the id registry so SDK `__del__` teardown still
  runs; a condition holding a `TGPythonInstanceWrapper` still never `__del__`s
  because every `TGObject` is strongly registered with no unregister path —
  pre-existing, out of scope, recorded as `xfail(strict)` in
  `tests/unit/test_tgcondition_cast_and_ids.py`.
- #9: the SDK `ChooseTargetSubsystem` loop appends the *parent* aggregator
  (`Preprocessors.py:833-836`), so a Disable order targets `Phasers`, not a
  bank — an SDK quirk, reproduced faithfully rather than fixed.
- #12: `BridgeSet.DeleteObjectFromSet` inherits the delete broadcast
  (harmless fourth site).
- #8: `SetWarpSequence` also detaches on `Abort`; headless in-set warps
  complete synchronously inside `Play()`, the rendered engine holds them open
  (`host_loop._flythrough_enabled`).
- #15: SDK `LostFocus` bodies never check `IsDead`, so teardown after
  `SetDead` is safe.
- Fixture rule learned across tasks: `ship._phaser = ...`-style private
  pokes are dead on `ShipClass`; use `SetPhaserSystem`/`SetTorpedoSystem`/…
  instead (every task's fixtures were corrected to match).

**Residuals (2026-09-20 fix wave) — the §2 statuses above overstate these
three; do not re-close them as done:**

- Gap #4: `ET_OBJECT_GROUP_OBJECT_ENTERED_SET`/`_EXITED_SET` are emitted;
  `ET_OBJECT_GROUP_CHANGED` still has no producer — the plan scoped it out.
- Gap #14: `ObjectDecloaked`, `TargetEnteredSet`, and `OurShipEnteredSet` are
  wired. `TargetListChanged` is NOT — it depends on `ET_OBJECT_GROUP_CHANGED`
  (gap #4), which is not emitted.
- Gap #5: `ConditionInRange.ProxDeleted` stays dead. It registers with
  target = the `ProximityCheck` object, but `ET_DELETE_OBJECT_PUBLIC` fires
  for objects leaving the world, not for proximity checks — the event and
  the registration target never match.
