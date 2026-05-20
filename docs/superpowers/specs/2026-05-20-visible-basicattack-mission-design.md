# Visible BasicAttack Mission (Slice E)

**Status:** spec — awaiting plan.
**Predecessors:** Slice A (BuilderAI + ConditionScript), Slice B (SelectTarget), Slice C (FireScript), Slice D1 (sub-Compound smokes), Slice D2 (PlainAI body ports — merged at `1e1800e`).
**Follow-on:** none for BasicAttack; mission objectives + weapon VFX are independent future work.

## Goal

Close the BasicAttack roadmap with a renderer-visible playthrough: launch `./build/dauntless`, load a BC combat mission, watch the hostile Cardassian Galor fly in and open fire on the Federation Galaxy. End state has two parts: (a) an automated headless integration test proving combat runs end-to-end through the host loop, and (b) a manual `./build/dauntless` observation documented in the task closure.

## Scope

**5 tasks:**
1. FedAttack smoke (Federation tactical Compound, sibling of NonFedAttack).
2. Headless M3Gameflow smoke via `gameloop_harness` — loads the SDK combat tutorial mission end-to-end; surfaces any remaining mission-script API gaps.
3. Renderer mission switch — env-var override on `engine.host_loop.run()` so M3Gameflow loads without disturbing the M2Objects-based ship-gate tests.
4. Visible-playthrough verification — automated headless renderer smoke + manual `./build/dauntless` observation.
5. Close the BasicAttack roadmap in the deferred AI-runtime doc.

**End states:**
- Automated: `pytest tests/integration/test_host_loop_m3gameflow.py` passes; the test runs ~30 seconds of mission time and asserts combat-relevant state (player hull damage > 0 OR weapon-hit events fired with the Galor as source).
- Manual: `./build/dauntless` with `OPEN_STBC_HOST_MISSION=Custom.Tutorial.Episode.M3Gameflow.M3Gameflow` runs; the implementer documents observing the Galor's BasicAttack behaviour for the task closure.

## Architecture

Four phases that progressively reduce uncertainty before the renderer-visible end state:

**Phase 1 — FedAttack symmetry.** Slice D2's engine surface fixes (PS_DONE semantics, CT_* subsystem matching, SetPreprocessingMethod pCodeAI wiring) should generalise to FedAttack. Mirror the NonFedAttack smoke; if anything surfaces, it's a small generalisation commit.

**Phase 2 — Headless mission script.** The existing `tools.gameloop_harness.run_mission_with_loop` boots an SDK mission via the same path the renderer uses, runs N ticks, returns `(status, exc, ticks)`. Pointing it at `Custom.Tutorial.Episode.M3Gameflow.M3Gameflow` runs the actual SDK combat tutorial: `PreLoadAssets` → `Initialize` → `CreateRegions` → `CreateStartingObjects` → `SetupAI` (wires Birian Galor with `AI.Compound.BasicAttack`) → `SetupEventHandlers` → `StartBriefingSequence`. Each surface gap (likely TGL loader, briefing-sequence stubs, mission-event handlers) → focused `feat(...)` commit.

**Phase 3 — Renderer mission switch.** Modify `engine.host_loop.run()` to honour `OPEN_STBC_HOST_MISSION` env var. Add a headless renderer smoke test running M3Gameflow for ~2 seconds (120 ticks). The test is marked `pytest.importorskip("_dauntless_host")` so it skips when the native extension isn't built — consistent with the existing `tests/integration/test_gameloop_harness.py` pattern.

**Phase 4 — Visible playthrough.** Extend the renderer smoke to ~30 seconds (1800 ticks) with combat-relevant assertions. Document the manual `./build/dauntless` observation. Close the BasicAttack roadmap.

### Surface boundaries

| File | What this slice adds |
|---|---|
| `tests/integration/test_fed_attack_smoke.py` (new) | FedAttack activation + multi-tick combat smoke (Task 1). |
| `tests/integration/test_m3gameflow_combat_smoke.py` (new) | Headless M3Gameflow end-to-end smoke via gameloop_harness (Task 2). |
| `tools/gameloop_harness.py` (possible modify) | If the harness doesn't expose final ship/event state, extend it with an optional return shape. ~20 LOC. (Task 2). |
| `engine/host_loop.py` (modify) | `OPEN_STBC_HOST_MISSION` env-var override on `run()` (Task 3). |
| `tests/integration/test_host_loop_m3gameflow.py` (new) | Headless renderer M3Gameflow smoke; `importorskip("_dauntless_host")` (Tasks 3+4). |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` (modify) | Close Slice E; archive BasicAttack roadmap (Task 5). |

## Components

### FedAttack smoke (Task 1)

Mirrors `tests/integration/test_non_fed_attack_smoke.py`:

```python
import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType,
    ImpulseEngineSubsystem, SensorSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game
# Fixture identical to NonFedAttack's; the only difference is the
# Compound name.
```

End assertion: `_speed_setpoint is not None` after 10 ticks. Reading the SDK FedAttack source at task time confirms the specific Compound semantics; the smoke is structurally identical to NonFedAttack's.

### Headless M3Gameflow smoke (Task 2)

```python
from tools.gameloop_harness import run_mission_with_loop

def test_m3gameflow_runs_60_ticks_no_crash():
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=60,
    )
    assert status == "pass", f"{exc}"
    assert exc is None
    assert ticks == 60
```

If the harness doesn't already provide a way to query post-run ship state, Task 2's plan extends the harness with an optional `return_state=True` flag that exposes the final mission/episode/game.

Combat assertion (stretch goal — if harness can expose state):
```python
# After 600 ticks at 60Hz (10s of game time), the Galaxy should have
# taken damage from the Galor.
state = run_mission_with_loop(..., n_ticks=600, return_state=True)
galaxy = state.set_manager.GetSet("Default").GetObject("Galaxy 1")
assert galaxy._hull.GetCondition() < galaxy._hull.GetMaxCondition()
```

### Renderer mission switch (Task 3)

In `engine/host_loop.py:run()`:

```python
def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    import os as _os_mod
    if mission_name is None:
        mission_name = _os_mod.environ.get(
            "OPEN_STBC_HOST_MISSION", SHIP_GATE_MISSION)
    # ... rest unchanged
```

Existing callers passing `mission_name=` explicitly are unaffected. New env-var path lets `./build/dauntless` swap missions without rebuilding.

### Visible playthrough (Task 4)

Automated `tests/integration/test_host_loop_m3gameflow.py`:

```python
import os
import pytest

pytest.importorskip("_dauntless_host")


def test_host_loop_runs_m3gameflow_with_combat(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from engine.host_loop import run
    rc = run(
        mission_name="Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        max_ticks=1800,  # 30s at 60Hz
    )
    assert rc == 0
    # Combat assertion: ship state post-run shows damage exchange.
    # Specific assertion shape pinned at task time after inspecting
    # what host_loop exposes for inspection.
```

Manual verification step (documented in Task 4's commit message):
> Launched `./build/dauntless` with `OPEN_STBC_HOST_MISSION=Custom.Tutorial.Episode.M3Gameflow.M3Gameflow`. Observed: Galaxy player ship loaded; Galor hostile appeared at distance ~XX; Galor closed range; phaser fire visible at frame ~YY; Galaxy hull condition dropped from 1.0 to ~0.ZZ over 30 seconds.

If actual weapon-fire VFX aren't rendered today, the manual observation notes that as a deferred item — the smoke still passes as long as the mission runs cleanly and combat events fire, even if they're invisible.

### Doc closure (Task 5)

In `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`, update the BasicAttack roadmap section to mark Slice E ✅ and archive it as a completed roadmap. If new deferred items surfaced during Slice E (e.g., weapon VFX rendering), add them to the existing "Out of scope (deferred to E)" sections of prior slices or to a new "Post-BasicAttack follow-ons" section.

## Data flow

```
Phase 1 (FedAttack smoke):
  pytest → FedAttack.CreateAI(ship) → tick_ai loop → assert combat

Phase 2 (Headless M3Gameflow):
  pytest → gameloop_harness.run_mission_with_loop("M3Gameflow", N)
    → importlib.import_module → mod.PreLoadAssets / Initialize
    → mission's SetupAI() wires Birian Galor with BasicAttack
    → engine.core.loop tick driver
    → return (status, exc, ticks) [+ state if Task 2 extends harness]

Phase 3 (Renderer mission switch):
  ./build/dauntless → host_main.cc → engine.host_loop.run_host_loop
    → engine.host_loop.run(mission_name=OPEN_STBC_HOST_MISSION or default)
    → _init_mission → same SDK module load + Initialize path as Phase 2
    → renderer per-tick: GameLoop.tick() + r.render_frame()

Phase 4 (Visible playthrough):
  Manual: ./build/dauntless OPEN_STBC_HOST_MISSION=... → observe + document.
  Automated: same as Phase 3, 1800 ticks under HEADLESS=1, assert combat.
```

## Error handling

Consistent with Slices A–D2:

- **Engine surface is permissive.** Missing SDK helpers return safe sentinels; SDK code is defensive.
- **Engine-gap escalation pattern.** Trivial gaps → focused `feat(...)` commit BEFORE the test commit. Novel gaps → STOP and report.
- **SDK scripts load unmodified.**
- **Test isolation.** Standard autouse `_isolate` fixtures for FedAttack smoke. Mission-running tests may need additional isolation (TGL loader state, mission-script module globals); handle per-task.
- **Renderer tests** `pytest.importorskip("_dauntless_host")` at module top so the suite skips them cleanly when the native extension isn't built. The non-renderer tasks (1, 2, 5) work without the native extension; the renderer tasks (3, 4) require it built.

## Testing strategy

5 tasks (one per phase + doc closure):

1. **FedAttack smoke** — Federation Compound symmetry with NonFedAttack. Expected ~zero engine gaps.
2. **Headless M3Gameflow smoke** — exercises full SDK mission init + run. Likely surfaces 2-4 small mission-script API gaps; each → focused `feat(...)` commit.
3. **Renderer mission switch** — env-var override + headless host-loop smoke (120 ticks). Surface dependent on what assumptions the renderer makes about mission shape.
4. **Visible-playthrough verification** — extend Task 3 smoke to 1800 ticks with combat assertions; document manual `./build/dauntless` observation in the commit message.
5. **Close BasicAttack roadmap** — mark Slice E ✅ in the deferred doc; archive the roadmap section.

## Out of scope (deferred to future)

- Real weapon-fire VFX (phaser beams, torpedo trails) — pure renderer/graphics work, separate stream.
- BasicAttack tactical-brain depth (`CheckGoodShot`, `WeaponTooDangerous`, `PredictTargetLocation`) — Slice C explicitly deferred these.
- Combat audio mixing — separate audio-subsystem work.
- Mission-objective scripting (M3Gameflow's nag-timer behaviour, victory conditions, briefing UI).
- `OptimizedFedAttack` / `OptimizedNonFedAttack` C-backed replacements — never; we run the Python.

These remain documented in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
