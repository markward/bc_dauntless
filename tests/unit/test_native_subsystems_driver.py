"""The native subsystem stage's driver (phase 6 A1, Task 2;
engine/appc/native_subsystems.py): every piece is still Python, handed back
by the native session one RUN_PYTHON record at a time, so the stage makes
exactly the calls the Python loop makes, in its order.

The per-tick state differential is
tests/integration/test_native_subsystems_differential.py.
"""
import random

import App
import pytest

from engine.appc import articulation
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.appc.subsystems import (CloakingSubsystem, PowerSubsystem,
                                    RepairSubsystem, ShieldSubsystem)
from engine.core import loop as game_loop
from tests.helpers import bc_assets, headless_mission

TICKS = 40      # past the first shield charge (tick 30 or 31)


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()


def _world(mp, native):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                  "DAUNTLESS_NATIVE_SUBSYSTEMS": "1" if native else "0"})
    assert native_subsystems.enabled() is native


def _spy(mp, calls):
    """Every one of the stage's five calls, logged (method, ship name) and
    then run."""
    def method(cls, label):
        orig = cls.Update

        def update(self, dt, _orig=orig):
            calls.append((label, self.GetParentShip().GetName(), dt))
            return _orig(self, dt)
        mp.setattr(cls, "Update", update)

    method(ShieldSubsystem, "shield")
    method(PowerSubsystem, "power")
    method(CloakingSubsystem, "cloak")
    method(RepairSubsystem, "repair")
    orig_tick = articulation.tick_ship

    def tick_ship(ship, dt, _orig=orig_tick):
        calls.append(("articulation", ship.GetName(), dt))
        return _orig(ship, dt)
    mp.setattr(articulation, "tick_ship", tick_ship)


def _run(native):
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        _world(mp, native)
        _spy(mp, calls)
        native_subsystems.reset_counts()
        for _ in range(TICKS):
            App.g_kTimerManager._time += game_loop.TICK_DELTA
            game_loop._update_ship_subsystems()
        counts = native_subsystems.counts()
    return calls, counts


def test_step_all_matches_the_python_stage_call_for_call():
    python, off = _run(native=False)
    native, on = _run(native=True)
    assert off["stages"] == 0, off
    assert on["stages"] == TICKS, on
    ships = {name for _, name, _ in python}
    assert len(ships) == 3, ships
    kinds = {k for k, _, _ in python}
    # A Warbird is in the cast: all five pieces run.
    assert kinds == {"shield", "power", "cloak", "repair", "articulation"}
    assert on["run_python"] > 0 and on["events"] == 0, on
    assert native == python


def test_a_ship_that_loses_a_subsystem_mid_walk(monkeypatch):
    """The driver asks the ship for each piece when its record comes, as the
    Python loop does: a handler (here, the shield Update) that detaches a
    LATER piece of the same ship removes that call, in both stages."""
    def run(native):
        calls = []
        with pytest.MonkeyPatch.context() as mp:
            _world(mp, native)
            _spy(mp, calls)
            orig = ShieldSubsystem.Update

            def update(self, dt, _orig=orig):
                _orig(self, dt)
                ship = self.GetParentShip()
                if ship.GetCloakingSubsystem() is not None:
                    ship._cloaking_subsystem = None
            mp.setattr(ShieldSubsystem, "Update", update)
            game_loop._update_ship_subsystems()
        return calls

    python = run(False)
    assert "cloak" not in {k for k, _, _ in python}
    assert run(True) == python


def test_a_row_dropped_mid_walk_is_still_updated():
    """A row freed mid-walk while its ship lives on (native_combat._drop: a
    value the mirror cannot hold) is not skipped: the Python stage still
    runs that ship's remaining pieces, so the native stage hands them back
    too (controller ruling, Task 2 fix round 1). Ship 0's shield Update
    drops ship 0's own row (between its pieces) and a LATER ship's."""
    from engine.appc.ship_iter import iter_non_rock_ships

    def run(native):
        calls = []
        with pytest.MonkeyPatch.context() as mp:
            _world(mp, native)
            ships = list(iter_non_rock_ships())
            assert all(isinstance(s.__dict__.get("_nslot"), int)
                       for s in ships)
            _spy(mp, calls)
            orig = ShieldSubsystem.Update
            dropped = []

            def update(self, dt, _orig=orig):
                _orig(self, dt)
                if self.GetParentShip() is ships[0] and not dropped:
                    for ship in (ships[0], ships[2]):
                        nc._drop(ship)
                        dropped.append(ship.__dict__.get("_nslot"))
            mp.setattr(ShieldSubsystem, "Update", update)
            for _ in range(2):
                game_loop._update_ship_subsystems()
            assert dropped == [None, None]      # the rows are gone
            assert native_subsystems.counts()["stages"] == (2 if native
                                                            else 0)
            names = [ships[0].GetName(), ships[2].GetName()]
        return calls, names

    python, names = run(False)
    # The dropped ships kept running: power, repair and articulation, both
    # ticks (the shield's own call is before the drop).
    for name in names:
        kinds = [k for k, n, _ in python if n == name]
        assert kinds.count("power") == kinds.count("repair") == \
            kinds.count("articulation") == 2, (name, kinds)
    native, _ = run(True)
    assert native == python


def test_the_switch(monkeypatch):
    """DAUNTLESS_NATIVE_SUBSYSTEMS: on unless exactly "0"; off without the
    live mirror."""
    monkeypatch.delenv("DAUNTLESS_NATIVE_SUBSYSTEMS", raising=False)
    for value, want in ((None, True), ("1", True), ("", True), ("0", False),
                        ("00", True)):
        env = {"DAUNTLESS_NATIVE_COMBAT": "1"}
        if value is not None:
            env["DAUNTLESS_NATIVE_SUBSYSTEMS"] = value
        nc.configure(env)
        assert native_subsystems.enabled() is want, value
    nc.reset()
    assert native_subsystems.enabled() is False


def test_the_event_table_holds_the_native_pieces_events():
    """Each native piece's event kinds have a handler (Task 3: the shield
    watchers); every kind the native session names has one."""
    events = native_subsystems._EVENTS
    assert set(events) == {"SHIELD_WATCHER", "SHIELD_WATCHER_TAIL"}
    assert set(native_subsystems._EVENT_HANDLERS) == set(events.values())


@pytest.mark.parametrize("target", [
    "engine.core.loop.iter_non_rock_ships",
    "engine.appc.ship_iter.iter_ships",
    "engine.appc.ship_iter.iter_non_rock_ships",
    "engine.appc.ship_iter.iter_set_objects"])
def test_a_patched_roster_runs_the_python_stage(monkeypatch, target):
    """The driver walks the sets itself, so a roster a caller patched (a
    test feeding the stage its own ships) sends the whole stage to the
    Python loop, which honours the patch."""
    ticked = []

    class _Bay:
        def Update(self, dt):
            ticked.append(dt)

    class _Ship:
        _bay = _Bay()

        def GetShieldSubsystem(self): return None
        def GetPowerSubsystem(self): return None
        def GetCloakingSubsystem(self): return None
        def GetRepairSubsystem(self): return self._bay

    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert native_subsystems.enabled()
    native_subsystems.reset_counts()
    if target == "engine.core.loop.iter_non_rock_ships":
        monkeypatch.setattr(target, lambda: [_Ship()])
    else:
        monkeypatch.setattr(target, lambda *a, **k: iter(()))
    monkeypatch.setattr(articulation, "tick_ship", lambda ship, dt: None)
    game_loop._update_ship_subsystems()
    counts = native_subsystems.counts()
    assert counts["stages"] == 0 and counts["patched_stages"] == 1, counts
    if target == "engine.core.loop.iter_non_rock_ships":
        assert ticked == [game_loop.TICK_DELTA]
    monkeypatch.undo()
    assert native_subsystems.enabled()


def test_a_callers_env_dict_without_the_switch_falls_back_to_the_process_env(
        monkeypatch):
    """native_combat.configure(env) with a caller's own dict: the dict's
    DAUNTLESS_NATIVE_SUBSYSTEMS wins when it names it; else the process
    environment's (fix round 1, Minor 1)."""
    combat = {"DAUNTLESS_NATIVE_COMBAT": "1"}
    monkeypatch.setenv("DAUNTLESS_NATIVE_SUBSYSTEMS", "0")
    nc.configure(combat)
    assert native_subsystems.enabled() is False
    nc.configure(dict(combat, DAUNTLESS_NATIVE_SUBSYSTEMS="1"))
    assert native_subsystems.enabled() is True
    monkeypatch.setenv("DAUNTLESS_NATIVE_SUBSYSTEMS", "1")
    nc.configure(dict(combat, DAUNTLESS_NATIVE_SUBSYSTEMS="0"))
    assert native_subsystems.enabled() is False
    nc.configure(combat)
    assert native_subsystems.enabled() is True
    monkeypatch.delenv("DAUNTLESS_NATIVE_SUBSYSTEMS")
    nc.configure(combat)
    assert native_subsystems.enabled() is True
