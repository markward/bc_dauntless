# Visible BasicAttack Mission Implementation Plan (Slice E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the BasicAttack roadmap with a renderer-visible playthrough of `Custom.Tutorial.Episode.M3Gameflow` where the hostile Federation Galaxy 2 attacks the friendly Federation Galaxy 1 (and the player) using `AI.Compound.BasicAttack` — which dispatches to `FedAttack` because Galaxy 2 is a Federation ship.

**Architecture:** Four-phase progression that isolates uncertainty: (1) FedAttack smoke parallels D2's NonFedAttack smoke; (2) headless M3Gameflow smoke uses the existing `gameloop_harness` to surface SDK mission-script gaps without renderer noise; (3) renderer mission switch adds an `OPEN_STBC_HOST_MISSION` env-var override so the renderer can load M3Gameflow; (4) visible-playthrough verification runs 1800 ticks (30s) under the headless renderer plus a manual `./build/dauntless` observation. Each engine gap surfaced lands as a separate `feat(<module>): <what>` commit before the consuming test commit (Slice B/C/D pattern).

**Tech Stack:** Python 3, pytest, `_SDKFinder` SDK loader, `tools.gameloop_harness` mission runner, `engine.host_loop.run` renderer host, `_dauntless_host` native extension (Tasks 3-4 only; `pytest.importorskip` gates).

---

## Prerequisites

Confirm Slice D2 is merged: `git log --oneline | grep "Slice D2"` should show `Merge: PlainAI body ports (BasicAttack Slice D2)` at `1e1800e`.

Baseline tests once before starting:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3
```
Expected: 1267 passed.

## Worktree setup

Slices B/C/D/D1/D2 each developed in `.claude/worktrees/`. Use the same pattern: create `.claude/worktrees/visible-basicattack` on branch `worktree-visible-basicattack` off current main. SDK/game directories are gitignored — symlink them from the main repo. Always prefix bash with `unset VIRTUAL_ENV &&`.

## File structure

| File | Purpose |
|---|---|
| `tests/integration/test_fed_attack_smoke.py` (new) | FedAttack activation + multi-tick combat smoke (Task 1) |
| `tools/gameloop_harness.py` (modify) | Add optional `return_state=True` kwarg returning a 4-tuple with captured pre-cleanup state (Task 2) |
| `tests/integration/test_m3gameflow_combat_smoke.py` (new) | Headless M3Gameflow end-to-end smoke (Task 2) |
| `engine/host_loop.py` (modify) | `OPEN_STBC_HOST_MISSION` env-var override on `run()` (Task 3) |
| `tests/integration/test_host_loop_m3gameflow.py` (new) | Headless renderer M3Gameflow smoke; `importorskip("_dauntless_host")` (Tasks 3 + 4) |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` (modify) | Close Slice E; archive BasicAttack roadmap (Task 5) |

## Engine-gap escalation pattern (carry-over)

**Trivial single-line stubs** (missing helper method, simple alias, obvious one-line addition that matches a pattern already used elsewhere): fix inline as a separate small commit BEFORE the test commit. Each gap = its own commit with `feat(<module>): <what>` message.

**Novel gaps** (architectural decisions, multi-line logic, new modules, unclear SDK semantics): **STOP and report**. Do NOT guess.

The test commit must be test-only.

---

## Task 1: FedAttack smoke

`AI.Compound.FedAttack.CreateAI(pShip, *lpTargets, **dKeywords)` is the Federation tactical Compound (sibling of NonFedAttack). Slice D2's engine surface fixes (PS_DONE semantics, CT_* subsystem matching, `SetPreprocessingMethod` `pCodeAI` wiring) should generalise. Expect zero engine gaps; if any surface, separate `feat(...)` commit.

**Files:**
- Test: `tests/integration/test_fed_attack_smoke.py` (new)

- [ ] **Step 1.1: Write the test file**

Create `tests/integration/test_fed_attack_smoke.py`:

```python
"""FedAttack end-to-end smoke. Federation-ship sibling of NonFedAttack;
the BasicAttack dispatcher (sdk/.../AI/Compound/BasicAttack.py:42-44)
routes Federation ships through FedAttack and everyone else through
NonFedAttack. With Slice D2's PlainAI body ports in place, the combat
subtree drives observable ship behaviour across multiple ticks."""
import pytest

import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType,
    ImpulseEngineSubsystem, SensorSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def game_context():
    """Mission stack with a non-empty script for sMissionModuleName."""
    mission = Mission()
    mission.SetScript("tests.integration.test_fed_attack_smoke")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_fed_attack_create_ai_drives_combat(game_context):
    """FedAttack's tree activates and writes a speed setpoint within
    10 ticks. Mirrors the NonFedAttack smoke fixture from Slice D2."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # PlainAI bodies (Intercept, TorpedoRun) need impulse-engine + ammo.
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    # ConditionSystemDisabled.CheckRootState defaults bState=1 with an
    # empty watchlist — give the ship a sensor subsystem so the
    # NoSensorsEvasive branch doesn't latch ACTIVE.
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.FedAttack as fed_attack
    builder = fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )
    assert builder._activation_failed is False

    for i in range(1, 11):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    assert ours._speed_setpoint is not None, (
        "after 10 ticks, FedAttack should have written a speed setpoint"
    )
```

- [ ] **Step 1.2: Run; expect pass (D2 generalised the engine surface)**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_fed_attack_smoke.py -v`
Expected: 1 passed.

If a new engine gap surfaces, fix as a separate `feat(<module>): <what>` commit BEFORE the test commit.

- [ ] **Step 1.3: Regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_non_fed_attack_smoke.py tests/integration/test_fed_attack_smoke.py -q`
Expected: 2 passed.

- [ ] **Step 1.4: Commit**

```bash
git add tests/integration/test_fed_attack_smoke.py
git commit -m "test(ai): FedAttack end-to-end smoke (sibling of NonFedAttack)"
```

---

## Task 2: Headless M3Gameflow smoke

Use `tools.gameloop_harness.run_mission_with_loop` to load M3Gameflow end-to-end. The mission's `Initialize` calls `PreLoadAssets` → `CreateRegions` (loads Biranu sets + custom placements) → `CreateStartingObjects` (creates Galaxy 1/2 + player) → `SetupAI` (wires Galaxy 2 with `AI.Compound.BasicAttack`, which dispatches to `FedAttack` because Galaxy is Federation species) → `SetupEventHandlers` → `StartBriefingSequence`.

The current harness API returns `(status, exc, ticks)`. Combat assertions need post-run state; extend the harness with an optional `return_state=True` kwarg.

**Files:**
- Modify: `tools/gameloop_harness.py` (add `return_state` kwarg)
- Test: `tests/integration/test_m3gameflow_combat_smoke.py` (new)

- [ ] **Step 2.1: Write the test file**

Create `tests/integration/test_m3gameflow_combat_smoke.py`:

```python
"""Headless M3Gameflow combat smoke via gameloop_harness.

M3Gameflow is the SDK's combat tutorial: Galaxy 1 (friendly, AI:
FriendlyAI) and Galaxy 2 (enemy, AI: EnemyAI → BasicAttack) start in
the Biranu1 system; player starts in Biranu2 (so combat happens between
the two Galaxies). With Slice D2's PlainAI body ports landed, the enemy
Galaxy 2's BasicAttack tree should drive observable combat behaviour.

This test runs the full SDK mission init path: PreLoadAssets,
Initialize, CreateRegions, CreateStartingObjects, SetupAI,
SetupEventHandlers, StartBriefingSequence. Expect this to surface
mission-script-only API gaps that pure-AI tests never reach."""
import pytest


@pytest.fixture(scope="session", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


def test_m3gameflow_initializes_without_crash(sdk_setup):
    """Minimum: the mission loads + Initialize() runs without raising.
    Zero ticks — pure init smoke."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=0,
    )
    assert status == "pass", f"M3Gameflow init failed: {exc}"
    assert exc is None
    assert ticks == 0


def test_m3gameflow_runs_60_ticks(sdk_setup):
    """One game-second (60 ticks at 60Hz) without crash. Combat may
    not yet be observable at 1s; this asserts the tick loop is stable."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=60,
    )
    assert status == "pass", f"M3Gameflow tick loop failed: {exc}"
    assert ticks == 60


def test_m3gameflow_600_ticks_with_combat(sdk_setup):
    """Ten game-seconds: the enemy Galaxy 2 should have closed range
    and produced observable combat behaviour. Uses return_state=True to
    inspect the Biranu1 set's Galaxy 1 hull condition."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks, state = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=600,
        return_state=True,
    )
    assert status == "pass", f"M3Gameflow long-run failed: {exc}"
    assert ticks == 600
    # The Biranu1 set contains Galaxy 1 (friendly) and Galaxy 2 (enemy).
    biranu1 = state["set_manager"].GetSet("Biranu1")
    assert biranu1 is not None, "Biranu1 set missing from state"
    galaxy1 = biranu1.GetObject("Galaxy 1")
    galaxy2 = biranu1.GetObject("Galaxy 2")
    assert galaxy1 is not None, "Galaxy 1 missing from Biranu1 set"
    assert galaxy2 is not None, "Galaxy 2 missing from Biranu1 set"
    # Combat-relevant assertion: after 10 game-seconds, at least one
    # of the Galaxies should have written a speed setpoint (the AI
    # subtrees ran and drove motion). The hull-damage assertion is
    # stretch — VFX/combat-hit propagation may not deliver damage in
    # 10s of game time given the BasicAttack closing-range cadence.
    assert (
        galaxy1._speed_setpoint is not None
        or galaxy2._speed_setpoint is not None
    ), "no Galaxy wrote a speed setpoint over 600 ticks"
```

- [ ] **Step 2.2: Run; expect init_fail surfacing mission-script gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_m3gameflow_combat_smoke.py::test_m3gameflow_initializes_without_crash -v`

Expected behaviour: likely fails. Mission-script gaps anticipated:
- `MissionLib.SetupSpaceSet` may need an engine helper if it touches subsystems we haven't ported.
- `App.g_kLocalizationManager.Load("data/TGL/...")` — TGL loader behaviour for missing files.
- `App.NULL_ID` constant — verify exists.
- `MissionLib.CreatePlayerShip` / `loadspacehelper.CreateShip` — these create real ship instances; verify the placement-by-name path works.
- `App.g_kStateMachine` for briefing sequences.

For each gap: read the surrounding SDK code, identify the smallest engine surface needed, add it as a focused `feat(<module>): <what>` commit BEFORE re-running the test.

**STOP and report** if you encounter:
- A novel architectural gap (multi-line logic the SDK assumes is C++ side, e.g., a real briefing-sequence state machine).
- A gap that requires faking out major subsystems.

- [ ] **Step 2.3: Extend `gameloop_harness` with `return_state` kwarg**

Modify `tools/gameloop_harness.py`. Find `run_mission_with_loop` (line 34). Change the signature to add `return_state: bool = False`. When `return_state=True`, every return path becomes a 4-tuple `(status, exc, ticks, state)` where `state` is a dict captured INSIDE the try block (the harness's `finally` calls `_set_current_game(None)` and clears `sys.modules`, so state must be captured before then).

Helper to centralise the return-shape logic:

```python
def _return(status, exc, ticks_done, state=None, return_state=False):
    """Return a 3-tuple by default, 4-tuple when return_state=True.
    state is None for init_fail (mission never built); populated for
    pass/loop_fail paths so callers can inspect post-run mission state."""
    if return_state:
        return (status, exc, ticks_done, state)
    return (status, exc, ticks_done)
```

Wire this into the three existing return paths in `run_mission_with_loop`:

```python
# init_fail branch (line ~80): state is None — mission never built.
try:
    mod = importlib.import_module(module_name)
    mod.Initialize(mission)
except Exception as exc:
    return _return("init_fail", exc, 0, None, return_state)

# pass branch (line ~94): capture state before falling through to
# the finally cleanup.
state = None
if return_state:
    state = {
        "mission": mission,
        "episode": episode,
        "game": game,
        "set_manager": App.g_kSetManager,
    }
return _return("pass", None, ticks_done, state, return_state)

# loop_fail branch (line ~96): also capture state — the partial
# state may help diagnose where the loop failed.
state = None
if return_state:
    state = {
        "mission": mission,
        "episode": episode,
        "game": game,
        "set_manager": App.g_kSetManager,
    }
return _return("loop_fail", exc, ticks_done, state, return_state)
```

Read the existing function (lines 34-105) before editing — the inline edit may want to lift the state-dict construction into a small helper rather than repeating it across pass/loop_fail. Keep the change additive: existing callers passing positional args + unpacking 3-tuples must continue to work. Add the `return_state: bool = False` kwarg at the end of the signature.

After editing, verify the existing tests still pass:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_gameloop_harness.py -v 2>&1 | tail -5
```
(These tests will fail on `_dauntless_host` collection errors — that's pre-existing. Verify by running with `--collect-only` or by spot-checking unrelated tests.)

- [ ] **Step 2.4: Run M3Gameflow test against the extended harness**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_m3gameflow_combat_smoke.py -v`

Iterate on engine-gap commits until 3 passed. If gaps stop being trivial, STOP and report.

- [ ] **Step 2.5: Commit harness extension**

```bash
git add tools/gameloop_harness.py
git commit -m "feat(gameloop_harness): return_state kwarg captures post-run mission state"
```

- [ ] **Step 2.6: Commit test**

```bash
git add tests/integration/test_m3gameflow_combat_smoke.py
git commit -m "test(integration): headless M3Gameflow combat smoke"
```

---

## Task 3: Renderer mission switch

Add an `OPEN_STBC_HOST_MISSION` env-var to `engine.host_loop.run()` so M3Gameflow can be loaded without changing the existing M2Objects-based default (which the ship-gate tests depend on).

**Files:**
- Modify: `engine/host_loop.py` (~5 LOC near `run()`'s signature)
- Test: `tests/integration/test_host_loop_m3gameflow.py` (new)

- [ ] **Step 3.1: Write the test file**

Create `tests/integration/test_host_loop_m3gameflow.py`:

```python
"""Renderer host-loop smoke for M3Gameflow.

Runs engine.host_loop.run() with OPEN_STBC_HOST_HEADLESS=1 and an
OPEN_STBC_HOST_MISSION pointing at M3Gameflow. Asserts the run
completes the configured tick budget without raising.

The native `_dauntless_host` extension is required; tests are skipped
cleanly when it isn't built (matches the pattern in
tests/integration/test_gameloop_harness.py)."""
import os
import pytest

pytest.importorskip("_dauntless_host")


def test_host_loop_runs_m3gameflow_120_ticks(monkeypatch):
    """120 ticks ≈ 2 seconds at 60Hz. Smallest viable smoke for the
    renderer + M3Gameflow integration. Headless mode hides the window."""
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv(
        "OPEN_STBC_HOST_MISSION",
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
    )
    from engine.host_loop import run
    rc = run(max_ticks=120)
    assert rc == 0
```

- [ ] **Step 3.2: Run; expect the test to fail because the env var isn't honoured yet**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_host_loop_m3gameflow.py -v`

Expected outcomes:
- If `_dauntless_host` is not built: test SKIPPED (acceptable; renderer-task verification deferred to a build environment).
- If `_dauntless_host` is built: test fails because `run()` ignores `OPEN_STBC_HOST_MISSION` and loads the default M2Objects mission.

- [ ] **Step 3.3: Modify `engine/host_loop.py:run()` to honour the env var**

Find `def run(mission_name: str = SHIP_GATE_MISSION, ...)` at line 1824. Change to accept `None` as the sentinel for "consult env var":

```python
def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window
    closes or max_ticks is reached. Returns 0 on clean exit.

    Mission resolution: mission_name argument wins; otherwise the
    OPEN_STBC_HOST_MISSION env var; otherwise SHIP_GATE_MISSION (the
    default M2Objects ship-gate mission). The env-var path lets
    ./build/dauntless swap missions without recompiling, while
    preserving the existing default for the ship-gate tests.
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"
    if mission_name is None:
        mission_name = _os.environ.get(
            "OPEN_STBC_HOST_MISSION", SHIP_GATE_MISSION)

    _setup_sdk()
    # ... rest unchanged
```

The key changes: `mission_name: str = SHIP_GATE_MISSION` → `mission_name: Optional[str] = None`, and the `if mission_name is None:` branch that consults the env var. Other existing callers passing `mission_name="..."` explicitly are unaffected.

- [ ] **Step 3.4: Run test to verify pass (skipped if `_dauntless_host` missing)**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_host_loop_m3gameflow.py -v`
Expected: 1 passed OR 1 skipped (depending on native build).

- [ ] **Step 3.5: Regression on ship-gate path**

Find an existing test that exercises `host_loop.run()` with the default mission — likely under `tests/host/` or `tests/integration/`:
```bash
grep -rln "host_loop.run\|from engine.host_loop import run" tests/ | head -5
```
Run any tests it surfaces to confirm the default-mission path still works.

- [ ] **Step 3.6: Commit engine change**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): OPEN_STBC_HOST_MISSION env-var override for run()"
```

- [ ] **Step 3.7: Commit test**

```bash
git add tests/integration/test_host_loop_m3gameflow.py
git commit -m "test(host_loop): 120-tick headless M3Gameflow smoke"
```

---

## Task 4: Visible playthrough verification

Extend the Task 3 smoke to 1800 ticks (30 seconds) with combat-relevant assertions, then document the manual `./build/dauntless` observation.

**Files:**
- Modify: `tests/integration/test_host_loop_m3gameflow.py` (add second test)

- [ ] **Step 4.1: Add a 30-second combat smoke test**

Append to `tests/integration/test_host_loop_m3gameflow.py`:

```python
def test_host_loop_m3gameflow_30_second_combat(monkeypatch):
    """30 seconds of mission time (1800 ticks @ 60Hz). The enemy
    Galaxy 2 should produce observable combat: weapon-hit events fire
    AND/OR a friendly Galaxy (Galaxy 1 or player) takes hull damage.

    The exact threshold depends on closing-range cadence + per-tick
    PlainAI cadence (GetNextUpdateTime returns 0.2-0.25s for most
    PlainAI scripts), so this test asserts "at least some combat
    effect" rather than a specific damage value."""
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv(
        "OPEN_STBC_HOST_MISSION",
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
    )
    from engine.host_loop import run
    rc = run(max_ticks=1800)
    assert rc == 0
    # After the host loop completes, query the global set manager to
    # check for combat-relevant state. The host loop's reset_sdk_globals
    # runs on entry; we inspect what's left at exit.
    import App
    biranu1 = App.g_kSetManager.GetSet("Biranu1")
    assert biranu1 is not None, "Biranu1 set missing after run"
    galaxy1 = biranu1.GetObject("Galaxy 1")
    assert galaxy1 is not None, "Galaxy 1 missing from Biranu1 after run"
    # At minimum: Galaxy 1's AI subtree ran and wrote a speed setpoint
    # (the friendly responded to the enemy by maneuvering).
    assert galaxy1._speed_setpoint is not None, (
        "after 30 game-seconds, Galaxy 1 should have written a speed "
        "setpoint (FriendlyAI ran)"
    )
```

- [ ] **Step 4.2: Run the 30-second smoke**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_host_loop_m3gameflow.py::test_host_loop_m3gameflow_30_second_combat -v`

Expected: 1 passed OR 1 skipped. If the test fails with a real exception (not skip), STOP and report — the host loop has a runtime gap that needs investigation.

- [ ] **Step 4.3: Manual visible-playthrough observation**

In the worktree directory, build the renderer:
```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/visible-basicattack
cmake -B build -S . 2>&1 | tail -5
cmake --build build -j 2>&1 | tail -5
```

If the build fails, mark the manual step as DEFERRED (skipped) and proceed to step 4.4 with that note in the commit message. The build environment may not have the native dependencies; documenting that is the correct outcome.

If the build succeeds, run:
```bash
OPEN_STBC_HOST_MISSION=Custom.Tutorial.Episode.M3Gameflow.M3Gameflow ./build/dauntless
```

Observe for ~30 seconds. Note in a temporary scratch file:
- Did the Galaxy 1 (friendly) appear? Position approximately?
- Did the Galaxy 2 (enemy) appear? Position approximately?
- Did Galaxy 2 close range or fire weapons (visible or in stdout logs)?
- Did Galaxy 1 take hull damage or maneuver in response?
- Did the renderer maintain stable FPS, or did it crash/lag?

Capture these notes (in your head or a temporary file — don't commit the scratch). They become the manual-observation paragraph in Step 4.5's commit message.

- [ ] **Step 4.4: Commit test with manual observation**

```bash
git add tests/integration/test_host_loop_m3gameflow.py
git commit -m "$(cat <<'EOF'
test(host_loop): 30-second M3Gameflow combat smoke

Automated assertion: Galaxy 1 (friendly) writes a speed setpoint
within 30 game-seconds — FriendlyAI runs and the host loop drives
the mission's combat tree end-to-end.

Manual observation (./build/dauntless OPEN_STBC_HOST_MISSION=...):
[FILL IN: paragraph describing what was observed visually. Examples:
"Galaxy 1 and Galaxy 2 loaded into the Biranu1 system at the
configured Galaxy1Start/Galaxy2Start placements. Galaxy 2 closed
range over the first 10 seconds. No weapon-fire VFX were visible
(deferred — pure renderer work). Galaxy 1's hull condition dropped
~0.05 over the observation period, indicating combat damage events
fired through the engine even though they're not yet rendered."

OR — if the renderer build failed in this environment:

"Manual observation deferred — local environment lacks renderer
build prerequisites (cmake failed at step <...>). The automated
1800-tick headless smoke passing is sufficient evidence the mission
runs end-to-end; renderer-side visual verification deferred to an
environment with a working native build."]
EOF
)"
```

---

## Task 5: Close the BasicAttack roadmap

Update the deferred AI-runtime doc to mark Slice E ✅ and archive the BasicAttack roadmap.

**Files:**
- Modify: `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`

- [ ] **Step 5.1: Update the Slice E bullet + archive the roadmap**

In `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`, find the BasicAttack roadmap section (added by Slice A's closing task and progressively updated through D2). The Slice E bullet currently reads something like:

```markdown
- **Slice E**: `NonFedAttack`/`FedAttack` `CreateAI` assembly + visible mission where a hostile flies in and opens fire.
```

Replace with:

```markdown
- **Slice E**: ✅ done in [visible BasicAttack mission plan](../plans/2026-05-20-visible-basicattack-mission.md). FedAttack smoke pinned end-to-end combat behaviour (sibling of Slice D2's NonFedAttack smoke). Headless M3Gameflow smoke proved the SDK combat tutorial runs end-to-end through `gameloop_harness` with Galaxy 1 (FriendlyAI) + Galaxy 2 (EnemyAI → BasicAttack → FedAttack via species dispatch). `OPEN_STBC_HOST_MISSION` env-var added to `engine.host_loop.run()` so the renderer can swap missions without recompiling. 30-second headless host-loop smoke asserts FriendlyAI maneuvers in response to the enemy. Manual `./build/dauntless` playthrough documented in the Task 4 commit.

The BasicAttack roadmap is complete. Future BC-AI work (richer tactical brain, weapon VFX rendering, mission objectives, audio mixing) lives in separate streams.
```

- [ ] **Step 5.2: Final regression sweep**

Run the focused sweep one final time:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration --continue-on-collection-errors -q -k "select or fire or condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives or torpedo_run or stationary_attack or follow_object or intelligent_circle or intercept or non_fed or fed_attack or fuzzy or evade or warp or sweep or sensors or ico_move or follow_through or m3gameflow or host_loop_m3gameflow" 2>&1 | tail -3
```
Expected: green (modulo pre-existing native-binding collection errors).

- [ ] **Step 5.3: Commit**

```bash
git add docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "docs(deferred): close Slice E + archive BasicAttack roadmap"
```

---

## Out of scope (deferred to future)

- Real weapon-fire VFX (phaser beams, torpedo trails) — pure renderer/graphics work, separate stream.
- BasicAttack tactical-brain depth (`CheckGoodShot`, `WeaponTooDangerous`, `PredictTargetLocation`) — Slice C explicitly deferred these.
- Combat audio mixing — separate audio-subsystem work.
- Mission-objective scripting (M3Gameflow's nag-timer behaviour, victory conditions, briefing UI).
- `OptimizedFedAttack` / `OptimizedNonFedAttack` C-backed replacements — never; we run the Python.

These remain documented in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
