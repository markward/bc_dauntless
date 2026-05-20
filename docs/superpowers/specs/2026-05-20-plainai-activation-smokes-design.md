# PlainAI Activation Smokes (Slice F)

**Status:** spec — awaiting plan.
**Predecessors:** Slices A–E (BasicAttack roadmap complete; merged at `6b37b81`).
**Follow-on:** none required; future kinematic-correctness work for these scripts can land per-script as missions need it.

## Goal

Cover the 17 unported PlainAI bodies (~3300 LOC of SDK) with per-script activation smoke tests, in one slice. Each test verifies that the PlainAI loads, configures via its required setters, and that one `Update()` call returns a valid `US_*` integer status — not a `_Stub` (which would indicate a silently-absorbed crash) and not an exception.

After Slice F: every PlainAI in `sdk/Build/scripts/AI/PlainAI/` has an engine-side activation guarantee. Kinematic correctness (does the ship actually maneuver right?) is explicitly deferred; the BasicAttack 5 PlainAI bodies that have full motion tests (Slice D2) remain the only ones with per-script behaviour assertions.

## Scope

**17 PlainAI scripts, batched by size into 5 tasks + doc closure:**

| Batch | Scripts | LOC range | Task # |
|---|---|---|---|
| Tiny | TriggerEvent, SelfDestruct, RunScript, RunAction | 69–88 | 1 |
| Medium-A | Defensive, Ram, ManeuverLoop, EvilShuttleDocking | 137–206 | 2 |
| Medium-B | Flee, TurnToOrientation, StarbaseAttack, EvadeTorps | 170–229 | 3 |
| Large-A | CircleObject, MoveToObjectSide, FollowWaypoints | 259–311 | 4 |
| Large-B | FollowThroughWarp (PlainAI body), Warp | 281–468 | 5 |
| Doc | Close Slice F in deferred doc | — | 6 |

Batching keeps each task to 3–4 scripts × ~80 LOC of test code = ~250–320 LOC per task. Comparable to Slice D1 task size.

## Architecture

Each test file under `tests/integration/test_<script_name>_smoke.py` (lowercase, snake_case from the SDK module name). The single test per file:

1. Build a minimal scene: ship in a set, optional target ship if the script needs one (read SDK `SetRequiredParams` to find out).
2. Instantiate via `PlainAI_Create(ours, "TestAI") + SetScriptModule("<ScriptName>")`.
3. Get the script instance via `GetScriptInstance()`.
4. Call required setters from the SDK's `SetRequiredParams` declaration.
5. Call `inst.Update()` once.
6. Assert the result is one of `App.ArtificialIntelligence.{US_ACTIVE, US_DONE, US_DORMANT, US_INVALID}` — a valid integer status, not a `_Stub`.

The `US_*` assertion is the load-bearing one: a `_Stub` return would slip through `pytest.raises` or a plain truthy check, but it isn't `int` and isn't `in {0, 1, 2, 3}`. The `isinstance(result, int)` + value check catches both genuine crashes (exception bubbles up) and silent stub absorption.

**Test isolation:** standard `autouse _isolate` fixture clearing `g_kSetManager._sets` + `g_kEventManager._method_handlers` (NOT `_broadcast_handlers`).

**Game-context fixture:** only the scripts that reach `pMission.GetScript()` need it. Most don't; per-task decisions when writing the test.

## Components

### Per-script test files (17 new)

`tests/integration/test_<script>_smoke.py`. Naming follows existing pattern:
- `test_trigger_event_smoke.py`
- `test_self_destruct_smoke.py`
- `test_run_script_smoke.py`
- `test_run_action_smoke.py`
- `test_defensive_smoke.py`
- `test_ram_smoke.py`
- `test_maneuver_loop_smoke.py`
- `test_evil_shuttle_docking_smoke.py`
- `test_flee_smoke.py`
- `test_turn_to_orientation_smoke.py`
- `test_starbase_attack_plainai_smoke.py` (suffix distinguishes from the Compound)
- `test_evade_torps_plainai_smoke.py` (suffix distinguishes from the Compound sub-Part)
- `test_circle_object_smoke.py`
- `test_move_to_object_side_smoke.py`
- `test_follow_waypoints_smoke.py`
- `test_follow_through_warp_plainai_smoke.py` (suffix distinguishes from the Compound)
- `test_warp_smoke.py`

### Engine surface

Anticipated gaps fall into a few categories that the plan author will encounter mid-batch:

- **`_AIScriptInstance` setters** missing for newly-exercised SDK setter calls — most degrade through `__getattr__`'s setter generator, but some may need explicit support (e.g., setters that the SDK reads back through `GetX` and the data-bag's auto-generator doesn't symmetrically support).
- **Ship/object accessors** the SDK reads but the engine doesn't have (e.g., a script that calls `pShip.GetEnergy()` if missing).
- **TG math helpers** (rare; Slice D2 added the major ones).
- **Conftest Py2 fixups** if any of the 17 scripts use a Py2 idiom not yet handled by `_fix_py2_syntax` / `_FixDictKeysIter` / etc.

Each gap → focused `feat(<module>): <what>` commit BEFORE the test commit that needs it.

## Data flow

```
test_<script>_smoke.py
  └─ _build_scene() → ours [+ target] in pSet
  └─ plain = PlainAI_Create(ours, "TestAI")
  └─ plain.SetScriptModule("<ScriptName>")            # loads via _SDKFinder
  └─ inst = plain.GetScriptInstance()                 # the SDK class instance
  └─ inst.Set<Required>(...)                          # per SetRequiredParams
  └─ result = inst.Update()                           # the load-bearing call
  └─ assert isinstance(result, int)
  └─ assert result in (
        App.ArtificialIntelligence.US_ACTIVE,
        App.ArtificialIntelligence.US_DONE,
        App.ArtificialIntelligence.US_DORMANT,
        App.ArtificialIntelligence.US_INVALID,
     )
```

## Error handling

Consistent with Slices A–E:

- **Engine surface is permissive.** Missing helpers return safe sentinels.
- **Engine-gap escalation pattern.** Trivial gaps → separate `feat(...)` commit before the consuming test commit. Novel gaps → STOP and report.
- **SDK scripts load unmodified.** Anything that crashes is fixed engine-side, never by patching `sdk/`.
- **Test isolation** as above.

### Per-batch escalation rule

Each task batch is 3–4 scripts. If a batch surfaces more than 3 engine gaps, the implementer should pause and assess: are these all small (one-line additions, alias methods, default-zero accessors)? If yes, continue with separate commits. If any gap requires multi-line logic or architectural decisions, STOP and report.

## Testing strategy

6 tasks:

1. **Tiny batch** — 4 scripts (TriggerEvent, SelfDestruct, RunScript, RunAction). Small bodies; most likely to surface "fire an event" / "run a callback" engine idioms cheaply.
2. **Medium-A batch** — 4 scripts (Defensive, Ram, ManeuverLoop, EvilShuttleDocking). Combat/motion bodies; share some engine surface with Slice D2's TorpedoRun.
3. **Medium-B batch** — 4 scripts (Flee, TurnToOrientation, StarbaseAttack, EvadeTorps). More motion + the EvadeTorps body (currently only exercised through the sub-Compound).
4. **Large-A batch** — 3 scripts (CircleObject, MoveToObjectSide, FollowWaypoints). Path/orbit kinematics; may share surface with IntelligentCircleObject and FollowObject.
5. **Large-B batch** — 2 scripts (FollowThroughWarp body, Warp). Warp logic + the largest single PlainAI; likely the heaviest engine-gap surface.
6. **Doc closure** — mark Slice F ✅ in `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`; note any per-script kinematic-correctness items deferred to future work.

## Out of scope

- **Kinematic correctness** of these 17 scripts. The smoke proves Update completes and returns a sensible status; it doesn't assert speed setpoints or turn vectors. Per-script behaviour testing lands when a mission needs it.
- **Conditions, Preprocessors, Compounds** — covered in their own future slices.
- **Tactical-brain depth** in the existing BasicAttack ports (Slice C explicitly deferred CheckGoodShot, etc.).
- **Weapon VFX rendering** — Phase 2 renderer work.

These remain documented in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
