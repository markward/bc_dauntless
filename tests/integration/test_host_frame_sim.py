"""host_loop._run_frame_sim runs real host frames headless (native motion
phase 4, Task 1): the frame's sim section, driven through
tests/helpers/host_frame_fight with the host's own controllers and a scripted
frame clock, carries its state across frames in the FrameSimContext."""
import importlib
import types

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.core.loop import GameLoop
from tests.helpers import bc_assets, headless_mission
from tests.helpers import host_frame_fight as hff

pytestmark = pytest.mark.skipif(_h is None, reason="native module not built")


@pytest.fixture
def two_ship_fight(monkeypatch):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    headless_mission.clear_in_flight()
    headless_mission.load(hff.MISSION)
    loop = GameLoop(owns_boundary=False)
    scene = types.SimpleNamespace(player=App.Game_GetCurrentPlayer())
    return scene, loop


def test_frame_sim_runs_headless_and_carries_its_state(monkeypatch,
                                                       two_ship_fight):
    scene, loop = two_ship_fight
    ctx = hff.headless_context(monkeypatch, scene, loop)
    results = hff.drive(ctx, (3, 0, 1), 3)
    assert [r.sim_ticks for r in results] == [3, 0, 1]
    assert 0.0 <= ctx.accumulator < ctx.tick_dt
    assert ctx.previous_real_time == host_loop._frame_clock()
    assert results[-1].player is App.Game_GetCurrentPlayer()


def test_headless_standins_mirror_the_real_surface():
    for target in hff.HEADLESS_STANDINS:
        mod_name, attr = target.split(":")
        assert hasattr(importlib.import_module(mod_name), attr), target
    real = host_loop.HostController()
    for name in hff.CONTROLLER_SURFACE:
        assert hasattr(real, name), name
        assert hasattr(hff._Controller(None), name), name


def test_published_equals_live_at_every_combat_step(monkeypatch):
    """Spec 2026-11-03 §6 (native motion phase 4, Task 4): no stage writes a
    ship pose between the motion stage's publish and the combat step, so at
    every _advance_combat entry each published row is the live store pose,
    bit for bit. Combat reading the published copy inside the window
    therefore changes no answer (the goldens are unchanged)."""
    from engine.appc import native_combat
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
    headless_mission.clear_in_flight()
    headless_mission.load(hff.MISSION)
    loop = GameLoop(owns_boundary=False)
    scene = types.SimpleNamespace(player=App.Game_GetCurrentPlayer())
    ctx = hff.headless_context(monkeypatch, scene, loop)
    checked = {"steps": 0, "rows": 0}
    real = host_loop._advance_combat

    def at_entry(*a, **k):
        assert _h.combat_motion_published_open()
        for h, pos, rot, _vel in _h.combat_motion_published()[1]:
            ship = native_combat._registry.get(h)
            p = ship.GetWorldLocation()
            assert ([x.hex() for x in pos] ==
                    [x.hex() for x in (p.x, p.y, p.z)]), ship.GetName()
            assert ([x.hex() for x in rot] ==
                    [x.hex() for x in ship.GetWorldRotation().as_tuple()]), \
                ship.GetName()
            checked["rows"] += 1
        checked["steps"] += 1
        return real(*a, **k)
    monkeypatch.setattr(host_loop, "_advance_combat", at_entry)
    hff.drive(ctx, hff.FRAME_TICKS, 60)
    assert checked["steps"] == sum(hff.FRAME_TICKS) * 60 // len(hff.FRAME_TICKS)
    assert checked["rows"] >= 8 * checked["steps"] // 2
