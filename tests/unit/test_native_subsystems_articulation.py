"""The native articulation piece (phase 6 A1, Task 6; subsystem_step.h THE
ARTICULATION PIECE): ``articulation.tick_ship``'s ``_rigless_key`` early-out
decided by the native stage, so a rigless ship costs no Python call. A rigged
ship, a ship never ticked, and a ship whose articulated-part generation moved
since it was found rigless still run ``tick_ship``, unchanged.
"""
import random

import App
import pytest

from engine.appc import articulated_part, articulation, effect_queue
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.appc.ship_iter import iter_non_rock_ships
from engine.core import loop as game_loop
from tests.helpers import bc_assets, headless_mission

SHIPS = 3


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


def _world(mp):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    ships = list(iter_non_rock_ships())
    assert len(ships) == SHIPS
    return ships


def _spy(mp):
    calls = []
    real = articulation.tick_ship

    def tick_ship(ship, dt, _real=real):
        calls.append(ship.GetName())
        return _real(ship, dt)
    mp.setattr(articulation, "tick_ship", tick_ship)
    return calls


def _tick(n=1):
    for _ in range(n):
        App.g_kTimerManager._time += game_loop.TICK_DELTA
        game_loop._update_ship_subsystems()
        effect_queue.boundary()


def _add_rig(leaf):
    part = articulated_part.ArticulatedPartProperty_Create("test wing")
    part.SetStateAngle("cruise", 10.0)
    part.SetStateAngle("red", 40.0)
    App.g_kModelPropertyManager.RegisterLocalTemplate(part)
    articulated_part.snapshot_for_leaf(leaf)


def _rigged(ship):
    return bool(articulation.rig_for(articulation.leaf_for(ship)))


def test_rigged_ship_still_runs_tick_ship(monkeypatch):
    ships = _world(monkeypatch)
    calls = _spy(monkeypatch)
    snap = dict(articulated_part._BY_LEAF)
    leaves = [articulation.leaf_for(s) for s in ships]
    assert len(set(leaves)) >= 2, leaves
    _add_rig(leaves[0])
    try:
        _check_rigged_vs_rigless(ships, calls)
    finally:
        articulated_part.restore(snap)


def _check_rigged_vs_rigless(ships, calls):
    rigged = [s.GetName() for s in ships if _rigged(s)]
    rigless = [s.GetName() for s in ships if not _rigged(s)]
    assert rigged and rigless, "the scene needs both kinds of ship"
    _tick(4)
    for name in rigged:
        assert calls.count(name) == 4, name
    # A rigless ship runs once (tick_ship finds it rigless), then never.
    for name in rigless:
        assert calls.count(name) == 1, name


def test_rig_added_at_runtime_starts_articulating(monkeypatch):
    ships = _world(monkeypatch)
    calls = _spy(monkeypatch)
    ship = next(s for s in ships if not _rigged(s))
    name = ship.GetName()
    _tick(3)
    assert calls.count(name) == 1
    leaf = articulation.leaf_for(ship)
    snap = dict(articulated_part._BY_LEAF)
    try:
        _add_rig(leaf)
        assert _rigged(ship)
        _tick(2)
        assert calls.count(name) == 3
        assert "test wing" in ship._articulation_poses or \
            ship._articulation_transitions is not None
    finally:
        articulated_part.restore(snap)
    # The rig is gone again: found rigless once more, then skipped.
    _tick(3)
    assert calls.count(name) == 4
