# Deferred: ship AI runtime (Plain/Compound AI dispatch)

**Status:** deferred 2026-05-18. The full `ArtificialIntelligence` class hierarchy is mirrored in [`engine/appc/ai.py`](../../../engine/appc/ai.py) but every node is a data container — no script is loaded, no `Update` is called, no ship motion happens. Mission scripts build AI trees during init and they sit inert.

## Desired end state

A ship spawned with a `PlainAI("Stay")` attached actually ticks: `Update()` runs at the cadence its `GetNextUpdateTime()` reports, returns US_ACTIVE, and zero motion is applied. From there the same dispatch path drives `GoForward` → `TurnToOrientation` → `Intercept` → `FollowObject` → `CircleObject` → a full `AI.Compound.BasicAttack` tree of priority-listed leaves with weapon preprocessors. Visible result: an enemy ship intercepting and engaging the player in the renderer.

## What's in the SDK we need to drive

86 Python files under [`sdk/Build/scripts/AI/`](../../../sdk/Build/scripts/AI/), preloaded by [`AI/Setup.py:GameInit`](../../../sdk/Build/scripts/AI/Setup.py). Layered:

| Layer | Count | Examples | Role |
|---|---|---|---|
| `PlainAI/*` | 30 | Stay, GoForward, Intercept, CircleObject, Flee, FollowObject, TurnToOrientation | Leaf behaviours. Each defines a class with `__init__(self, pCodeAI)`, `GetNextUpdateTime()` (seconds), and `Update()` returning a US_* status. |
| `Compound/*` | 14 | BasicAttack, FedAttack, CloakAttack, DockWithStarbase | `CreateAI(pShip, *targets, **flags)` factories that build PriorityList/Sequence trees of PlainAIs + preprocessors. |
| `Compound/Parts/*` | 5 | EvadeTorps, ICOMove, SweepPhasers, WarpBeforeDeath, NoSensorsEvasive | Sub-graphs that compound AIs splice in. |
| `Player/*` | 24 | DestroyFreely, DisableAft, InterceptTarget, OrbitPlanet, PlayerWarp | Trees built when the player issues a tactical order. |
| `Fleet/*` | 5 | DefendTarget, DestroyTarget, HelpMe | Wingman orders. |
| `Preprocessors.py` | 1 | OptimizedFireScript, OptimizedSelectTarget | Per-tick "decide before child runs" hooks (target selection, weapon firing). |

Conditions: 30 modules under [`sdk/Build/scripts/Conditions/`](../../../sdk/Build/scripts/Conditions/) — each a class instantiated by `ConditionScript_Create(module, class, *args)`, evaluated each tick to feed `SetStatus`.

## Primitive class surface (Appc side)

From [`sdk/Build/scripts/App.py:4922-5232`](../../../sdk/Build/scripts/App.py):

- **`ArtificialIntelligence`** — base. Statuses US_ACTIVE / US_DONE / US_DORMANT / US_INVALID. `IsActive`, `HasFocus`, `Pause`, `Unpause`, `SetInterruptable`, `Reset`, `GetID`, `GetName`, `GetObject`, `GetShip`.
- **`PlainAI`** — `SetScriptModule(name)` imports `AI.PlainAI.<name>`, instantiates the class with `pCodeAI=self`, exposes the instance via `GetScriptInstance()`. The script reaches through `self.pCodeAI.GetShip()` for all motion + weapon calls. `StopCallingActivate()` ends one-shot Activate dispatch.
- **`PriorityListAI`** — `AddAI(ai, priority)`, `RemoveAI`, `RemoveAIByPriority`. Highest-priority non-DORMANT child runs.
- **`SequenceAI`** — `AddAI`, `RemoveAI`, `RemoveAIByIndex`, `GetAI(idx)`, `SetLoopCount` (`LOOP_INFINITE = -1`), `SetResetIfInterrupted`, `SetDoubleCheckAllDone`, `SetSkipDormant`. Advances on child DONE.
- **`RandomAI`** — `AddAI`. Picks at random.
- **`PreprocessingAI`** — `SetContainedAI(ai)`, `SetPreprocessingMethod(instance, method_name)` (two-arg form is the modern path, used by E7M2/E7M3), `GetPreprocessingInstance()`, `ForceUpdate`, `ForceDormantStatus`, `ForceStatusChange`. Statuses PS_NORMAL / PS_SKIP_ACTIVE / PS_SKIP_DORMANT / PS_DONE — preprocess return value gates whether contained AI runs that tick. Also FDS_NORMAL / FDS_TRUE / FDS_FALSE for forced-dormant override.
- **`ConditionalAI`** — `SetContainedAI`, `AddCondition`. Contained AI runs iff condition status is active.
- **`BuilderAI`** (subclass of PreprocessingAI) — lazy construction; `AddAIBlock`, `AddDependency`, `AddDependencyObject`.
- **`AIScriptAssist`**, **`OptimizedFireScript`**, **`OptimizedSelectTarget`** — preprocessing flavours specialised for weapon firing and target selection.

Scheduling lives in `TimeSliceProcess` ([`App.py:4468-4492`](../../../sdk/Build/scripts/App.py)) and `PythonMethodProcess` ([`App.py:4494-4511`](../../../sdk/Build/scripts/App.py)) — priorities UNSTOPPABLE / CRITICAL / NORMAL / LOW, `SetDelay`, `SetDelayUsesGameTime`, `SetFunction`, `Update`. The AI ticker plugs into these.

## What the engine currently has — and is missing

[`engine/appc/ai.py`](../../../engine/appc/ai.py) covers the class shapes:

- All hierarchy classes exist with the right method names (`AddAI`, `SetContainedAI`, `SetPreprocessingMethod`, etc.) but no execution semantics.
- `_AIScriptInstance` (line 129) is a catch-all `Set*/Get*` proxy that records into a dict and is returned by `PlainAI.GetScriptInstance()`. Real SDK scripts never run.
- `TGCondition` / `ConditionScript` capture the spec (module name, class name, args) but never load or evaluate.
- `ConditionEventCreator.ConditionChanged` does re-fire its event into `g_kEventManager` — that path works.
- `BuilderAI` captures the dependency graph but does not activate blocks.

Missing entirely:

- `PlainAI.RegisterExternalFunction(name, dict)` — called by [`BaseAI.SetExternalFunctions`](../../../sdk/Build/scripts/AI/PlainAI/BaseAI.py); currently absorbed by `__getattr__` as a no-op.
- `TimeSliceProcess` / `PythonMethodProcess` shims (not searched, not in `engine/appc/`).
- AI tick driver in [`engine/host_loop.py`](../../../engine/host_loop.py) — line 1990 comments acknowledge "Python AI runs in the gameloop tick above" but no AI Update is invoked anywhere.
- Ship motion APIs on `ShipClass`: `TurnTowardLocation`, `SetSpeed(speed, dir, frame)`, `SetTargetAngularVelocityDirect`, `InSystemWarp(target, dist)`, `StopInSystemWarp`, `GetPredictedPosition(p,v,a,t)`, `GetRelativePositionInfo`. `GetVelocityTG` exists at [`engine/appc/objects.py:216`](../../../engine/appc/objects.py).
- Real `ConditionScript` evaluation — instantiate the named class, call its evaluator, feed `SetStatus`.

## The six implementation steps

### Step 1 — Real script loading in `PlainAI`

In `PlainAI.SetScriptModule(name)`: `__import__("AI.PlainAI." + name)`, locate the class, instantiate it with `pCodeAI=self`, store as `_script_instance`. `GetScriptInstance()` returns the real object. Add `RegisterExternalFunction(name, dict)` on `PlainAI` so `BaseAI.SetExternalFunctions` ([`BaseAI.py:54`](../../../sdk/Build/scripts/AI/PlainAI/BaseAI.py)) actually records the mapping. Same change for `PreprocessingAI.SetPreprocessingMethod` two-arg form — already keeps the caller's instance; one-arg form should also import a module if that path is exercised (probably not; grep before deciding).

### Step 2 — Shim `TimeSliceProcess` + `PythonMethodProcess`

New module (probably `engine/appc/time_slice.py`). Min surface: `SetPriority`, `GetPriority`, `SetDelay`, `GetDelay`, `SetDelayUsesGameTime`, `GetDelayUsesGameTime`, `SetFunction(method)`, `Update`. Back with a single priority-ordered scheduler. Time source per `SetDelayUsesGameTime`: game time via `g_kTimerManager` (scaled — confirmed in [memory:project_time_scaling]) vs real time via `g_kRealtimeTimerManager`. NORMAL and LOW are the only priorities actually used by Python (CLAUDE.md notes CRITICAL/UNSTOPPABLE are C++-internal).

### Step 3 — AI tick driver in the host loop

Walk the AI tree top-down each frame:

- `PreprocessingAI` → call the bound preprocess method on its instance, branch on PS_*: PS_NORMAL runs the contained AI, PS_SKIP_ACTIVE skips the child but stays active, PS_SKIP_DORMANT marks dormant, PS_DONE completes. Read [`AI/Preprocessors.py`](../../../sdk/Build/scripts/AI/Preprocessors.py) first to confirm the contract — especially `OptimizedFireScript` and `OptimizedSelectTarget`, which are the load-bearing preprocessors in real combat trees.
- `PriorityListAI` → run the highest-priority non-DORMANT child; promote to DONE when all children DONE.
- `SequenceAI` → run current child; on DONE advance, loop per `_loop_count`.
- `RandomAI` → pick one (seeded? confirm by static read).
- `ConditionalAI` → if condition active, run contained; else US_DORMANT.
- `PlainAI` → if elapsed ≥ `GetNextUpdateTime()`, call `Update()`, honor the returned US_* and reschedule.

Driver runs from the same 60 Hz tick used elsewhere — CLAUDE.md notes Q1 closed at 60 Hz fixed and Q2 closed at AI/Python first within the tick, so the AI driver fires at the start of frame before physics + render.

### Step 4 — Ship motion APIs on `ShipClass`

Bind to PyBullet rigid bodies (Phase 1 harness) and the C++ engine later:

- `TurnTowardLocation(vec)` — ✅ done in [Ship AI Intercept plan](../plans/2026-05-18-ship-ai-intercept.md). Thin wrapper on `TurnDirectionsToDirections`.
- `SetTargetAngularVelocityDirect(vec)` — ✅ done in Steps 1-3 plan; defensive copy in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md).
- `SetSpeed(speed, direction, frame)` — ✅ done; defensive copy added in motion slice. `SetImpulse` alias added.
- `GetPredictedPosition(p, v, a, t)` — ✅ done in motion slice.
- `GetRelativePositionInfo(vec)` — ✅ done in motion slice; row→col convention fix in commit `68f6220`.
- `InSystemWarp(target, distance)` — ✅ done in [Ship AI Intercept plan](../plans/2026-05-18-ship-ai-intercept.md). Stateless teleport-to-near-target. Renderer-side visuals (streaks, camera flash) are a separate follow-up.
- `StopInSystemWarp()` — ✅ done; no-op in the stateless model.
- `GetImpulseEngineSubsystem().GetMaxSpeed()` / `GetMaxAccel()` — ✅ exist on the subsystem; motion integrator + TurnDirectionsToDirections solver use them.

### Step 5 — End-to-end smoke trail, one leaf at a time

1. **`PlainAI.Stay`** ([`Stay.py`](../../../sdk/Build/scripts/AI/PlainAI/Stay.py)) — ✅ done in [Steps 1-3 plan](../plans/2026-05-18-ship-ai-runtime-step1-3.md).
2. **`PlainAI.GoForward`** — ✅ done in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md). `SetImpulse` aliased to `SetSpeed`; linear ramp + position integration land in `engine/appc/ship_motion.py`.
3. **`PlainAI.TurnToOrientation`** — ✅ done in [Ship AI Motion plan](../plans/2026-05-18-ship-ai-motion.md). `TurnDirectionsToDirections` solver in `engine/appc/ships.py`; angular ramp + rotation integration in `engine/appc/ship_motion.py`.
4. **`PlainAI.Intercept`** ([`Intercept.py`](../../../sdk/Build/scripts/AI/PlainAI/Intercept.py)) — ✅ done in [Ship AI Intercept plan](../plans/2026-05-18-ship-ai-intercept.md). Closes the gap on the canonical "turn + thrust + warp + prediction" hard-case. Obstacle avoidance still no-op (ProximityManager stub). `bMoveInFront=1` branch correct but untested end-to-end; first NonFedAttack test will cover it.
5. **`PlainAI.FollowObject` + `CircleObject`** — still open; `GetRelativePositionInfo` is now available (landed in the motion slice).
6. **`AI.Compound.BasicAttack`** — still open.

### Follow-up after Intercept

- **Renderer warp visuals.** `InSystemWarp` currently teleports kinematically with no visual treatment. When the chase-camera / particle / motion-blur subsystems land, hook them in via a renderer-side pass; the engine-side teleport stays correct.
- **Obstacle avoidance.** `Intercept.AdjustDestinationForLargeObstacles` runs but is a no-op because `ProximityManager.GetLineIntersectObjects` returns `()`. Real avoidance lands when the proximity subsystem itself gets real work (planet avoidance, large-ship avoidance, line-sphere geometry helper).

### Step 6 — `ConditionScript` actually evaluates

`ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange", *args)` should `__import__` the module, instantiate the class with `*args`, and feed its evaluator into `SetStatus`. The 30 condition classes under [`sdk/Build/scripts/Conditions/`](../../../sdk/Build/scripts/Conditions/) are mostly short predicates over ship state (range, line-of-sight, system disabled, attacked-by, in-set, timer elapsed). Most don't need per-tick evaluation — they're event-driven (e.g. `ConditionAttacked` flips when a damage event lands). Decide per-class whether the evaluator runs each tick or only on the relevant event.

## Decisions to nail down before Step 3

1. **PreprocessingAI return semantics** — confirm PS_SKIP_ACTIVE / PS_SKIP_DORMANT / PS_DONE behavior by reading [`AI/Preprocessors.py`](../../../sdk/Build/scripts/AI/Preprocessors.py). The contract drives the tree-walk in Step 3.
2. **`GetNextUpdateTime` time source** — game time (scales with `SetTimeRate`) or real time? Per CLAUDE.md Q3 finding (game time scales 0.204×), AI naturally slows with time scale — almost certainly game time. Confirm by checking what timer the original engine uses inside `TimeSliceProcess.SetDelayUsesGameTime` default.
3. **`StopCallingActivate` semantics** — current shim is a no-op; SDK uses it to disable repeated Activate calls once a subclass-specific Activate is satisfied. Likely fine as a no-op for the smoke trail but revisit before BasicAttack.
4. **Save/load** — 39 SDK classes use `__getstate__`/`__setstate__`. `PythonMethodProcess` cannot be pickled and must be recreated in `__setstate__` (per CLAUDE.md). Defer all save/load AI work until interactive missions run end-to-end.
5. **AI lifetime / ownership** — when does an AI graph get garbage-collected? `RemoveAI` paths exist on all composite types; need to confirm whether removal cascades to TimeSliceProcess deregistration.

## Files in scope

| File | Relevance |
|---|---|
| [`engine/appc/ai.py`](../../../engine/appc/ai.py) | All hierarchy classes; rewrite `PlainAI`/`PreprocessingAI`/`ConditionScript` to load + dispatch scripts |
| `engine/appc/time_slice.py` (new) | `TimeSliceProcess` + `PythonMethodProcess` scheduler |
| [`engine/appc/ships.py`](../../../engine/appc/ships.py) | Add motion APIs (`TurnTowardLocation`, `SetSpeed`, `SetTargetAngularVelocityDirect`, `InSystemWarp`, `GetPredictedPosition`, `GetRelativePositionInfo`) |
| [`engine/host_loop.py`](../../../engine/host_loop.py) | AI tick driver insertion point (~line 1990, before the existing physics/render comment) |
| [`App.py`](../../../App.py) | Root-level shim re-exports — add `TimeSliceProcess`, `PythonMethodProcess`, motion helpers if any cross over |
| [`sdk/Build/scripts/AI/PlainAI/BaseAI.py`](../../../sdk/Build/scripts/AI/PlainAI/BaseAI.py) | Reference for `RegisterExternalFunction` / `SetupDefaultParams` / `SetRequiredParams` contracts |
| [`sdk/Build/scripts/AI/Preprocessors.py`](../../../sdk/Build/scripts/AI/Preprocessors.py) | Read first for PS_* contract; defines `OptimizedFireScript` / `OptimizedSelectTarget` |
| [`sdk/Build/scripts/AI/Setup.py`](../../../sdk/Build/scripts/AI/Setup.py) | Module preload list — every AI module the engine expects to be importable |
| [`sdk/Build/scripts/loadspacehelper.py`](../../../sdk/Build/scripts/loadspacehelper.py) | How ships acquire AI at construction (per CLAUDE.md line 54-135 is the physics-integration site; AI attach is nearby) |

## Test plan when implementing

- Headless: pytest-driven smoke tests that spawn a ship with one PlainAI and assert (a) `Update` is invoked at the expected cadence, (b) the ship's velocity/angular setpoints change after Update.
- After Step 4: PyBullet-backed test that an `Intercept` AI closes on a stationary target inside N seconds.
- After Step 5 step 6 (Compound BasicAttack): integration test with the player ship and a hostile in the same set — confirm hostile turns toward player, opens fire when in range, and the weapon emitters actually fire (existing [`engine/appc/combat.py`](../../../engine/appc/combat.py) infrastructure).
- Renderer-side smoke: visible hostile intercepting the player in `build/dauntless`. Watch for hitches when `AI.Setup.GameInit` preloads all 86 modules at mission start — Setup currently runs but every import is a near-no-op; once scripts have real bodies, loading time matters.

## Out of scope / explicitly deferred inside this work

- Multiplayer AI sync (`SetIsHost` / `SetMultiplayer` paths).
- Save/load round-trip for AI graphs.
- AI Editor tooling (the `#AIFlag` / `#AIGroup` comments scattered through Compound modules).
- Difficulty flag tuning ([`Compound/BasicAttack.py:g_lFlagThresholds`](../../../sdk/Build/scripts/AI/Compound/BasicAttack.py) is data-driven and will be tuned once gameplay is observable).
