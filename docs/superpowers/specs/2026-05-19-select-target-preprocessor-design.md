# SelectTarget Preprocessor — Design (BasicAttack Slice B)

**Status:** brainstormed 2026-05-19. Next step: implementation plan in `docs/superpowers/plans/`.

**Slice B of the BasicAttack roadmap.** Slices C–E (`FireScript` preprocessor, Compound sub-graphs, `FedAttack`/`NonFedAttack` assembly + visible smoke) sit on top of the target selection this slice ships.

**Builds on:** [Slice A: BuilderAI + ConditionScript](2026-05-18-builder-ai-conditions-design.md) (merged 2026-05-18 as `48c4c72` + `2a90e40`). The AI-driver preprocessing dispatch, the broadcast method handler, `TGPythonInstanceWrapper`, the event-type constants, and `ConditionScript` eager instantiation are all the foundation this slice consumes.

## Goal

Make the SDK's `AI.Preprocessors.SelectTarget` work end-to-end so combat Compound trees (`NonFedAttack`, `FedAttack`, `CloakAttack`, `TractorDockTargets`) can pick targets dynamically using the SDK's weighted-factor rating. After this slice, a synthetic `PreprocessingAI` whose preprocess instance is a real `SelectTarget` over an `ObjectGroup` of three candidate ships will:
1. Score each candidate via `GetTargetRating` (distance, in-front angle, is-current-target, shield/weapon/hull state, damage taken, priority, popularity).
2. Pick the highest-scored candidate.
3. Call `pOurShip.SetTarget(chosen)` if `bSetShipTarget` is true.
4. Walk the contained AI subtree, find every AI whose `GetExternalFunctions()` registers `"SetTarget"`, and dispatch `getattr(script_instance, info["FunctionName"])(target_name)` on each — propagating the chosen target through the tree so leaf AIs (e.g. `Intercept` configured to track a name) follow it.

Pinned with regression tests; the integration test exercises both the rating math and the SetTarget chain.

## Non-goals

- The "Optimized" Pyrex-backed `SelectTarget` (SDK comments note a C-accelerated replacement). We run the Python class directly — identical behavior, slower at large scale.
- Player-AI integration (`UsePlayerSettings` → `Bridge.TacticalMenuHandlers.AutoTargetChange`). Player tactical menu wiring lands when the player-AI work happens in a later slice.
- Sensor-visibility logic (`TargetVisible` etc.). SelectTarget's default `self.bIgnoreSensors = 1` keeps every target visible regardless of LOS, sensor range, or jamming. Real sensor evaluation is a separate subsystem out of scope.
- Damage-event accumulation correctness under fast-firing scenarios. The slice wires the `DamageEvent` handler but doesn't stress-test rapid hits — the per-source running totals are observable but their semantics under burst fire are deferred.
- Time-budgeted `UpdateTargetInfo` correctness under frame pressure. We pass a generous deadline (`game_time + 1.0`) so `UpdateTargetInfo` always completes in one call. Real frame-budget enforcement lands when the renderer host needs it.

## Architecture

### AI-driver preprocess signature widening

Current `_tick_preprocessing` calls `getattr(inst, method)()` with no args. SelectTarget's `Update(dEndTime)` expects a deadline. Solution: introspect the bound method's signature with `inspect.signature` once at preprocess time; if the method takes one positional arg (beyond `self`), pass `game_time + 1.0`. Otherwise call with no args (preserves existing synthetic-preprocess tests). The introspection happens once per tick, not per AI — cached on the `PreprocessingAI` instance the first time it's seen.

### Engine surface additions

| Surface | Behavior | Reason |
|---|---|---|
| `App.g_kSystemWrapper.GetTimeSinceFrameStart()` | Returns `0.0` | SelectTarget compares against `dEndTime`; with deadline = game_time + 1.0 the always-zero return keeps us inside the budget. No real frame timer in Phase 1. |
| `App.TGProfilingInfo_EndTiming(token)` | No-op | SDK calls `EndTiming`; we have `_StopTiming` already. Add the alias. |
| `App.ET_DECLOAK_BEGINNING` | Integer constant | Event-type registration for `ObjectDecloaked` handler. Value picked to avoid existing constants. |
| `ShieldSubsystem.GetShieldPercentage()` | Sum-current/sum-max across 4 faces; fallback 1.0 when no max | Read by SelectTarget rating to penalize ships with full shields. |
| `ShipClass.GetCloakingSubsystem()` | Returns `None` (stub) | FedAttack/NonFedAttack check `if pShip.GetCloakingSubsystem(): use_cloak = True`. None keeps the non-cloak path live. |
| `WeaponHitEvent.GetFiringObject()` | Alias for `GetSource()` | SelectTarget's damage handler reads `GetFiringObject()`. |
| `ObjectGroupWithInfo.__getitem__(name)` | Returns the per-name info dict (or `{}` for missing) | Rating reads priority info via `pGroupWithInfo[sTarget]["Priority"]`. |
| `ShipClass.StartGetSubsystemMatch(CT_WEAPON_SYSTEM)` honors filter | Iterator returns only weapon-class subsystems when filter is `CT_WEAPON_SYSTEM` | Rating walks weapon systems to compute `fWeaponsGood`. Existing iterator may not honor the type filter — verify and fix. |
| `Subsystem.GetCombinedConditionPercentage()` on weapon/hull subsystems | `condition / max_condition` (fallback 1.0) | May already exist on one class; ensure consistent behavior across weapon/hull/shield. |

All additions are small mechanical stubs except `ShieldSubsystem.GetShieldPercentage` and the subsystem-filter behavior, which need light arithmetic.

### External-SetTarget-dispatch chain

When SelectTarget picks a new target, it iterates two sources of AIs to call `SetTarget` on:
1. `self.lAdditionalSetTargetAITrees` — list of AI IDs the caller explicitly added via `AddSetTargetTree(pAI)`.
2. The contained AI subtree under the owning `PreprocessingAI` (`self.pCodeAI._contained_ai` and recursively into composites).

For each AI in those sources, it reads `pAI.GetExternalFunctions()` (returns a dict registered via `PlainAI.RegisterExternalFunction` from the prior slice; SDK callers do this in `BaseAI.SetExternalFunctions`). If the dict has `"SetTarget"`, the info contains `{"FunctionName": "SetObjectName"}` (or similar). The dispatch then calls `getattr(pAI.GetScriptInstance(), "SetObjectName")(target_name)` to set the target on that leaf.

We add a small helper `iter_ais_with_external_function(root_ai, fname)` in `engine/appc/ai.py` that yields PlainAI instances in the subtree whose `_external_functions` dict has `fname`. SelectTarget can use it via `App.<helper>` exposure or directly via subtree walking the AI tree shape (PriorityListAI._ais, SequenceAI._ais, ConditionalAI._contained_ai, PreprocessingAI._contained_ai, BuilderAI._contained_ai).

### Damage-event integration

SelectTarget's `DamageEvent(pEvent)` is registered via `g_kEventManager.AddBroadcastPythonMethodHandler(ET_WEAPON_HIT, wrapper, "DamageEvent")` during construction. The handler accumulates `pEvent.GetDamage() / pHull.GetMaxCondition()` into `self.dDamageReceived[source.GetObjID()]`. The Slice A method-handler dispatch routes this automatically. The slice does NOT introduce any new event flow — just ensures SelectTarget can register and that `GetFiringObject` / `GetDamage` work on `WeaponHitEvent`.

## Components / file map

| File | Change | LOC |
|---|---|---|
| [`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py) (modify) | `_tick_preprocessing` introspects preprocess signature; passes `game_time + 1.0` when method accepts one arg | ~25 |
| [`App.py`](../../../App.py) (modify) | `ET_DECLOAK_BEGINNING` constant; `TGProfilingInfo_EndTiming` alias; `g_kSystemWrapper.GetTimeSinceFrameStart()` returning 0.0 | ~20 |
| [`engine/appc/subsystems.py`](../../../engine/appc/subsystems.py) (modify) | `ShieldSubsystem.GetShieldPercentage()`; verify `GetCombinedConditionPercentage` exists consistently on weapon/hull subsystems and ensure subsystem-type-filtered iteration honors `CT_WEAPON_SYSTEM` | ~50 |
| [`engine/appc/ships.py`](../../../engine/appc/ships.py) (modify) | `GetCloakingSubsystem()` returning None; ensure subsystem-match iteration uses the filter when given | ~15 |
| [`engine/appc/events.py`](../../../engine/appc/events.py) (modify) | `WeaponHitEvent.GetFiringObject()` alias for `GetSource()` | ~5 |
| [`engine/appc/objects.py`](../../../engine/appc/objects.py) (modify) | `ObjectGroupWithInfo.__getitem__(name)` returning per-name dict | ~10 |
| [`engine/appc/ai.py`](../../../engine/appc/ai.py) (modify) | `iter_ais_with_external_function(root_ai, fname)` helper walking the AI tree shape | ~40 |
| `tests/unit/test_select_target_rating.py` (new) | 7 tests: load `AI.Preprocessors.SelectTarget`, set factor weights, assert `GetTargetRating` produces expected scores for distance / in-front / shields-down / damage-source / no-priority / popularity / current-target boost. | ~180 |
| `tests/unit/test_select_target_dispatch.py` (new) | 5 tests: 3 candidate ships, one `Update`, assert chosen target is highest-rated; assert `SetTarget` callback fired on a leaf AI registered via `RegisterExternalFunction`; assert no-target case returns `PS_SKIP_DORMANT`; assert no-op when no targets eligible; assert `bSetShipTarget=1` calls `pShip.SetTarget`. | ~150 |
| `tests/integration/test_select_target_in_priority_list.py` (new) | 3 tests: SelectTarget under a PriorityListAI containing 2 candidate AI branches, run multiple ticks, confirm dispatch + target propagation across ticks, confirm damage-event integration shifts target preference. | ~140 |
| `tests/integration/test_ai_driver_preprocess_arg.py` (new) | 3 tests: AI driver passes `dEndTime` to a 1-arg preprocess method; calls 0-arg method without args; cached signature lookup doesn't re-call signature on second tick. | ~70 |
| [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md) (modify) | Strike Slice B; note forward refs C/D/E | ~5 |

Total ~700 LOC. Slightly larger than Slice A but in line with prior slices' actual size after engine-gap expansion.

## Implementation sequencing (preview for the plan)

1. **AI-driver preprocess signature widening.** Foundation: 0-arg vs 1-arg method dispatch + signature cache. Unit-tested with synthetic preprocess instances. Doesn't touch SelectTarget yet.
2. **Engine surface stubs** (constants, no-op profiling, `GetTimeSinceFrameStart`, `GetCloakingSubsystem`, `GetFiringObject` alias). Cheap mechanical commits, each its own tiny test if needed.
3. **Subsystem percentage accessors** + subsystem-type-filter iteration. Unit tests on each accessor.
4. **`iter_ais_with_external_function` helper.** Unit tests against synthetic AI trees (PriorityList, Sequence, Conditional, Preprocessing composites).
5. **`SelectTarget` rating math.** Load via `_SDKFinder`, exercise `GetTargetRating` directly with controlled inputs.
6. **`SelectTarget` dispatch chain.** End-to-end target picking + `SetTarget` propagation.
7. **`SelectTarget` in a PriorityListAI integration test.** Validates the slice end-to-end.
8. **Deferred-doc close-out.**

Each task = one TDD cycle. Same shape as prior slices.

## Risks + open questions

1. **AI-driver introspection performance.** `inspect.signature` per tick per `PreprocessingAI` is slow. Mitigation: cache the result on the `PreprocessingAI` instance after first call. Risk: `PreprocessingAI` subclasses may inherit a `_preprocess_accepts_endtime` attr that's wrong. Action: cache on a private attr unique to this slice (e.g. `_preprocess_arity_cache`) and invalidate when the preprocessing instance changes.

2. **`ObjectGroup_ForceToGroup(*pTargetGroup)` semantics.** SelectTarget's constructor takes `*pTargetGroup` (variadic). The SDK helper handles single-name, list, or existing ObjectGroup. We have this from prior slices — verify the variadic-args case works.

3. **`pCodeAI` back-reference.** SelectTarget reads `self.pCodeAI.ForceUpdate()`, `IsActive()`, `GetShip()`. These are on `PreprocessingAI` / `ArtificialIntelligence`. `ForceUpdate` may not yet do anything meaningful in our AI driver (it's supposed to cause the AI to run on the next tick without waiting for cadence). Action: implement `ForceUpdate` to reset the cadence timer so the AI fires on the next driver pass. ~10 LOC if missing.

4. **Subsystem iteration filter.** SelectTarget's `GetTargetRating` calls `pShip.StartGetSubsystemMatch(App.CT_WEAPON_SYSTEM)` and iterates. Need to verify our existing match iterator actually filters by type. If it returns all subsystems regardless, the `fWeaponsGood` rating averages across non-weapon subsystems too — degrades rating quality but doesn't break the test. Action: confirm by reading `engine/appc/ships.py`'s `StartGetSubsystemMatch`; fix if it ignores the filter.

5. **`bSetShipTarget=1` writes to `pShip.SetTarget(pChosen)`.** Our `ShipClass.SetTarget` exists and stores the target. Verify SelectTarget passes the ship instance (not the name string) when setting target. The SDK does `pOurShip.SetTarget(pNewTarget)` with the ship object, so this should work.

6. **Slice scope creep risk if many SDK ship-state queries surface.** GetTargetRating reads 7+ ship state accessors. If 2–3 of them turn out to be missing or wrong, the slice grows. Mitigation: each surface gap is its own small commit (Subtract / Unitize pattern from Intercept). Stay disciplined.

## What this unlocks

- Slice C (`FireScript`): can register `"SetTarget"` external function; SelectTarget drives it. Slice C also reuses the preprocess-signature widening from this slice.
- Slice E (`FedAttack` / `NonFedAttack`): both compound trees include `SelectTarget` as their primary preprocess. After this slice they can construct with a real target picker.
- `ConditionAttacked` (Slice C dependency) shares the `DamageEvent` handler pattern wired here.
