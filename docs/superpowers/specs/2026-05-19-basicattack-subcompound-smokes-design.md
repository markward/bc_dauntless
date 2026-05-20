# BasicAttack Sub-Compound Smokes (Slice D1)

**Status:** spec — awaiting plan.
**Predecessors:** Slice A (BuilderAI + ConditionScript), Slice B (SelectTarget), Slice C (FireScript — merged at `db1c608`).
**Follow-ons:** Slice D2 (PlainAI body ports: `TorpedoRun`, `StationaryAttack`, `IntelligentCircleObject`, `FollowObject`, Intercept polish), Slice E (NonFedAttack/FedAttack visible mission).

## Goal

Pin per-sub-Compound activation behaviour so the NonFedAttack/FedAttack tree's failure modes bisect to a specific sub-Compound. Today, Slice C's `test_non_fed_attack_smoke.py` xpasses — meaning the whole Compound activates — but we have no per-sub-Compound coverage. If a sub-Compound regresses in a later slice, the parent smoke won't pinpoint which one. D1 adds that pinpointing.

## Scope

**Slice D was originally framed as one slice covering "PlainAI sub-graphs that FedAttack/NonFedAttack splice in" (~1800 LOC of SDK). Split by type:**

- **D1 (this spec):** the 6 sub-Compounds NonFedAttack/FedAttack splice in — 5 in `AI/Compound/Parts/` plus `AI.Compound.FollowThroughWarp`. ~470 LOC of SDK. Activation-smoke depth only.
- **D2 (future):** the 5 PlainAI scripts (`TorpedoRun`, `StationaryAttack`, `IntelligentCircleObject`, `FollowObject`, Intercept polish). ~1300 LOC of SDK. Real `Update` body behaviour.

**D1 end state:** each of the 6 sub-Compounds has a focused smoke test. NonFedAttack continues to xpass (we don't touch the parent test). When D2 + E land, the parent test will tighten naturally.

## Architecture

Six smoke tests under `tests/integration/`, one per sub-Compound. Each test:
1. Builds a minimal ship + (where the SDK signature needs one) a target via the established Slice B/C fixture pattern.
2. Imports the sub-Compound module via `_SDKFinder` and calls its `CreateAI(pShip, ...)`.
3. Asserts the returned AI is non-None and has the expected immediate-child structure (read from the SDK source).
4. Calls `tick_ai` once or twice; asserts no crash and that the tree's status is sensible (`US_DORMANT` for the default-flags case in most).

No new engine modules. Engine gaps may surface but are anticipated to be small (a missing setter on `_AIScriptInstance`, a `SetInterruptable` no-op) and handled via the engine-gap escalation pattern from Slices B/C: each gap → focused `feat(<module>): <what>` commit before the test commit.

The SDK sub-Compound modules load via `_SDKFinder` unchanged. PlainAI script instances they create (`TorpedoRun`, `IntelligentCircleObject`, etc.) load via the same mechanism but their `Update` bodies are NOT exercised in D1 — that's D2's job.

### Surface boundaries

| File | What this slice adds |
|---|---|
| `tests/integration/test_evade_torps_smoke.py` | EvadeTorps activation smoke |
| `tests/integration/test_warp_before_death_smoke.py` | WarpBeforeDeath activation smoke |
| `tests/integration/test_sweep_phasers_smoke.py` | SweepPhasers activation smoke |
| `tests/integration/test_no_sensors_evasive_smoke.py` | NoSensorsEvasive activation smoke |
| `tests/integration/test_ico_move_smoke.py` | ICOMove activation smoke (most elaborate — nested PriorityListAI/ConditionalAI) |
| `tests/integration/test_follow_through_warp_smoke.py` | FollowThroughWarp activation smoke (full Compound, not a Part) |
| `engine/appc/ai.py` (if needed) | Stubs for any `_AIScriptInstance` setters / AI-tree helpers that surface |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` | Slice D1 closure note + forward-ref D2/E |

## Components

### Sub-Compound `CreateAI` signatures

Each task reads the actual SDK signature before constructing the call. As inventoried during brainstorming:

- `EvadeTorps.CreateAI(pShip, sTorpSource=None, dKeywords={})` — confirmed at `sdk/Build/scripts/AI/Compound/Parts/EvadeTorps.py:3`.
- `WarpBeforeDeath.CreateAI(pShip, dKeywords={})` — verify by reading at plan time.
- `SweepPhasers.CreateAI(pShip, sTarget, dKeywords={})` — verify.
- `NoSensorsEvasive.CreateAI(pShip, dKeywords={})` — verify.
- `ICOMove.CreateAI(pShip, sTarget, dKeywords, fForwardBias=0.0)` — confirmed at `sdk/Build/scripts/AI/Compound/Parts/ICOMove.py:3`.
- `FollowThroughWarp.CreateAI(pShip, sTarget, dKeywords={})` — verify.

### Expected tree shapes

Per sub-Compound, the smoke test asserts the immediate-child structure. As an example, `EvadeTorps` returns a `ConditionalAI` named "IncomingTorps" wrapping a `PlainAI` named "EvadeTorps" (per `Parts/EvadeTorps.py:31-39`). `ICOMove` returns a `PriorityListAI` named "ICOMovePriorities" with three children (`UseShields`, `UseSideWeapons_2`, `ICO_MoveNoWeaponsNoShields`) per `Parts/ICOMove.py:122-128`.

Each task's smoke test asserts the equivalent for its sub-Compound — read the SDK at task time, hard-code the expected names/types.

### Common helper

```python
def _build_scene_with_target():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target
```

Sub-Compounds whose `CreateAI` takes a target name use this fixture; sub-Compounds without a target (EvadeTorps, WarpBeforeDeath, NoSensorsEvasive) use a single-ship variant.

### Game-context fixture

The Slice C `test_non_fed_attack_smoke.py` uses `engine.core.game.Game/Episode/Mission/_set_current_game` to set a non-empty `pMission.GetScript()`. Slice D1 sub-Compounds are smaller and probably don't reach `GetScript()` — but each task's plan confirms by reading the SDK before deciding. If a sub-Compound needs it, the fixture is one fixture import + one decorator per test.

## Data flow

```
test_<sub_compound>_smoke.py
  └─ _build_scene[_with_target]()                   → ours [, target] in pSet
  └─ import AI.Compound.Parts.<X>                   → loaded via _SDKFinder
  └─ ai = <X>.CreateAI(ours, ...)                   → SDK builds AI tree using
                                                       App.PlainAI_Create, App.ConditionScript_Create,
                                                       App.ConditionalAI_Create, App.PriorityListAI_Create
  └─ assert immediate-child structure
  └─ tick_ai(ai, game_time=0.01)                    → recursive walk; PlainAI Update bodies
                                                       are present but Slice C says they only need
                                                       to not crash (D2 makes them behave)
  └─ assert no exception + sensible status
```

The path through `tick_ai` exercises:
- The AI driver's per-AI-type dispatch (already covered by Slices A-C).
- Any first-tick init paths (e.g., the `_ensure_select_target_initialized` / `_ensure_fire_script_initialized` analogs added in Slices B-C — these gate on specific markers and won't fire for these sub-Compounds).
- Each PlainAI's `Update` (degrades to the `_AIScriptInstance` data-bag fallback if the SDK script doesn't load, or runs the SDK body if it does).

The smoke tests don't care what `Update` does internally; only that the tree builds and a tick completes without exception.

## Error handling

Consistent with Slices B-C:

- **No engine surface added unless a test forces it.** Each gap is a small focused `feat(...)` commit BEFORE the test commit. Bisect-friendly.
- **Novel gaps (architectural decisions, multi-line logic, new modules) → STOP and report.** Same rule.
- **SDK scripts load unmodified.**
- **Conditions degrade gracefully via Slice A's lazy fallback.** `ConditionScript_Create` with an unknown module returns a fallback condition. Slice D1 does NOT port new Conditions (`ConditionFlagSet`, `ConditionIncomingTorps`, etc.) — they stay deferred until Slice E exercises them via mission flags.
- **Test isolation autouse fixtures** clear `g_kSetManager._sets` + `g_kEventManager._method_handlers`. Do NOT clear `_broadcast_handlers`.

## Testing strategy

Seven tasks:

1. **EvadeTorps smoke** — pin the pattern. Likely surfaces the most engine-gap stubs (first sub-Compound exercised in isolation).
2. **WarpBeforeDeath smoke** — read its CreateAI, verify the tree.
3. **SweepPhasers smoke** — read its CreateAI.
4. **NoSensorsEvasive smoke** — read its CreateAI.
5. **ICOMove smoke** — biggest Part (130 LOC, 4 PlainAI instances, nested PriorityListAI/ConditionalAI). Most likely to surface gaps.
6. **FollowThroughWarp smoke** — full Compound, not a Part. May behave differently; biggest unknown.
7. **Update deferred AI-runtime doc** — close Slice D1; forward-ref D2 (PlainAI bodies) and E.

The NonFedAttack xpass test from Slice C is NOT tightened in D1. It naturally flips once D2 + E land.

## Out of scope (deferred to D2, E)

- Real `Update` behaviour of `TorpedoRun`, `StationaryAttack`, `IntelligentCircleObject`, `FollowObject`. Slice D2.
- `Intercept` polish (Slice A landed an initial port; behaviour gaps may exist). Slice D2.
- Real Condition ports beyond Slice A's two (`ConditionExists`, `ConditionInRange`). Lazy fallback continues to cover the rest. Slice E (or wherever a mission needs a specific Condition).
- Tightening the NonFedAttack xpass. Slice E.
- `OptimizedFedAttack`/`OptimizedNonFedAttack` C-backed replacements — never; we run the Python.

These remain noted in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
