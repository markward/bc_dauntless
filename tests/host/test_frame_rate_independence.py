"""Game systems advance by the game time a frame covers, at any frame rate.

The host loop runs the GameLoop as many fixed 60 Hz ticks as the frame's wall
time accumulates (engine/core/timestep.py): several on a slow frame, none on a
fast one. Anything else that steps game state from the frame loop has to step
by the same amount. Weapons and combat did not: they advanced by one TICK_DT
per drawn frame. A 64-ship fight runs 3-5 ticks a frame, so torpedoes flew at
a third to a fifth of their speed (the player out-flew their own shots), phaser
damage arrived as slowly while shields recharged at full rate (nothing took
damage), and every particle played in slow motion. Above 60 fps, frames that
ran no tick still advanced combat, so it ran fast.

Two guards:
  - the real run() driven by a fake frame clock at 15 and 120 fps: every
    consumer receives exactly the game time the GameLoop advanced;
  - a structural check: inside run(), TICK_DT may only be handed to a call
    that runs once per tick, so a new once-per-frame consumer cannot quietly
    reintroduce the bug.
"""
import ast
import inspect
import os

import pytest

from tests.helpers import bc_assets

TICK_DT = 1.0 / 60.0
_MISSION = "Custom.Tutorial.Episode.M1Basic.M1Basic"


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    """run() reaches mods.install(); keep it off the developer's real mods/
    (same isolation as tests/host/test_host_loop_unit.py)."""
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def _run_at(monkeypatch, frame_dt, frames):
    """Run the real host loop for `frames` frames, each `frame_dt` long by
    the frame clock. Returns (game ticks, {consumer: summed dt})."""
    galaxy = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")
    if not galaxy.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")

    from engine import host_loop as hl
    from engine.appc.nebula_runtime import NebulaTracker
    from engine.appc.radiation import RadiationDriver
    from engine.core.loop import GameLoop

    now = [1000.0]

    def clock():
        now[0] += frame_dt
        return now[0]
    monkeypatch.setattr(hl, "_frame_clock", clock)

    ticks = [0]
    real_tick = GameLoop.tick

    def tick(self, *a, **k):
        ticks[0] += 1
        return real_tick(self, *a, **k)
    monkeypatch.setattr(GameLoop, "tick", tick)

    got = {}

    def record(name, dt):
        got[name] = got.get(name, 0.0) + dt

    real_weapons, real_combat = hl._advance_weapons, hl._advance_combat
    real_audio = hl.tick_audio

    def weapons(ships, dt, *a, **k):
        record("weapons", dt)
        return real_weapons(ships, dt, *a, **k)

    def combat(ships, dt, *a, **k):
        record("combat", dt)
        return real_combat(ships, dt, *a, **k)

    def audio(*, dt, **k):
        record("audio", dt)
        return real_audio(dt=dt, **k)
    monkeypatch.setattr(hl, "_advance_weapons", weapons)
    monkeypatch.setattr(hl, "_advance_combat", combat)
    monkeypatch.setattr(hl, "tick_audio", audio)

    real_neb, real_rad = NebulaTracker.update, RadiationDriver.update

    def neb(self, pset, ships, dt, *a, **k):
        record("nebula", dt)
        return real_neb(self, pset, ships, dt, *a, **k)

    def rad(self, ships, dt, *a, **k):
        record("radiation", dt)
        return real_rad(self, ships, dt, *a, **k)
    monkeypatch.setattr(NebulaTracker, "update", neb)
    monkeypatch.setattr(RadiationDriver, "update", rad)

    assert hl.run(_MISSION, max_ticks=frames) == 0
    return ticks[0], got


@pytest.mark.parametrize("fps", [15, 120])
def test_every_consumer_gets_the_game_time_the_loop_advanced(monkeypatch, fps):
    frames = 40
    ticks, got = _run_at(monkeypatch, 1.0 / fps, frames)
    # The scenario really is a slow / fast frame rate.
    if fps < 60:
        assert ticks > frames * 2
    else:
        assert 0 < ticks < frames
    game_time = ticks * TICK_DT
    for name in ("weapons", "combat", "nebula", "radiation", "audio"):
        assert name in got, "%s never ran" % name
        assert got[name] == pytest.approx(game_time, abs=1e-9), (
            "%s advanced %.4f s while the game advanced %.4f s at %d fps"
            % (name, got[name], game_time, fps))


# --- structural guard ---------------------------------------------------------

# Calls that legitimately take TICK_DT outside the per-tick loop: the
# accumulator that DECIDES how many ticks a frame runs.
_ALLOWED = {"step_accumulator"}


def _callee(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _is_per_tick_loop(node):
    """`for ... in range(_sim_ticks_this_frame)`."""
    it = getattr(node, "iter", None)
    return (isinstance(node, ast.For) and isinstance(it, ast.Call)
            and getattr(it.func, "id", None) == "range"
            and any(isinstance(a, ast.Name) and a.id == "_sim_ticks_this_frame"
                    for a in it.args))


def test_tick_dt_is_only_handed_to_per_tick_calls():
    import engine.host_loop as hl

    tree = ast.parse(inspect.getsource(hl))
    run_fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run")
    parent = {}
    for node in ast.walk(run_fn):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def per_tick(node):
        while node in parent:
            node = parent[node]
            if _is_per_tick_loop(node):
                return True
            if isinstance(node, ast.FunctionDef) and node.name == "_tick_gameloop":
                return True
        return False

    offenders = []
    for call in (n for n in ast.walk(run_fn) if isinstance(n, ast.Call)):
        values = list(call.args) + [k.value for k in call.keywords]
        if not any(isinstance(v, ast.Name) and v.id == "TICK_DT" for v in values):
            continue
        if _callee(call) in _ALLOWED or per_tick(call):
            continue
        offenders.append("line %d: %s(...)" % (call.lineno, _callee(call)))
    assert not offenders, (
        "run() hands one fixed tick to a call that runs once per FRAME; a "
        "frame runs 0..15 ticks, so it advances at the wrong rate. Step it in "
        "`for _ in range(_sim_ticks_this_frame)`, or pass the frame's game "
        "time (_frame_game_dt):\n  " + "\n  ".join(offenders))
