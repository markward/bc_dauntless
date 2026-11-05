"""The native subsystem stage's driver (phase 6 A1, Task 2;
engine/appc/native_subsystems.py): every piece not yet native
(articulation; shields are native since Task 3, power since Task 4, cloak
and repair since Task 5) is handed back by the native session one
RUN_PYTHON record at a time, so the stage makes exactly the calls the
Python loop makes, in its order.

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
                                    RepairSubsystem)
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


def _spy(mp, calls, pieces=False):
    """Every Python call of the stage, logged (method, ship name) and then
    run: articulation (and, with `pieces`, the plant's, the cloak's and the
    bay's Update). The shield, power, cloak and repair pieces are native
    (Tasks 3-5) and a patched Update of theirs is not honoured (spec §3
    "Mods and patches (Part A)"), so they are not spied on by default: the
    counts and the differential cover them."""
    def method(cls, label):
        orig = cls.Update

        def update(self, dt, _orig=orig):
            calls.append((label, self.GetParentShip().GetName(), dt))
            return _orig(self, dt)
        mp.setattr(cls, "Update", update)

    if pieces:
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
    assert kinds == {"articulation"}
    # ... and every shield, power, cloak and repair piece was native: one
    # record (articulation's) per ship per stage.
    assert on["run_python"] == 1 * 3 * TICKS, on
    assert native == python


def test_a_ship_that_loses_a_subsystem_mid_walk(monkeypatch):
    """A handler that detaches a LATER piece removes that piece, in both
    stages: the Python loop asks the ship's getter when it gets there, the
    native walk reads the ship's ref then (the detach pushed it). Here the
    first ship's articulation detaches the next ship's cloak and bay while
    the cloak is mid-transition and the bay has work: neither moves that
    tick."""
    from engine.appc.ship_iter import iter_non_rock_ships

    def run(native):
        with pytest.MonkeyPatch.context() as mp:
            _world(mp, native)
            ships = list(iter_non_rock_ships())
            victim = next(s for s in ships[1:]
                          if s.GetCloakingSubsystem() is not None)
            cloak = victim.GetCloakingSubsystem()
            bay = victim.GetRepairSubsystem()
            sub = victim.GetSensorSubsystem()
            sub.SetCondition(sub.GetMaxCondition() * 0.5)
            bay._queue.append(sub)
            cloak.StartCloaking()
            game_loop._update_ship_subsystems()
            before = (cloak._transition_elapsed, sub._condition)
            orig_tick = articulation.tick_ship

            def tick_ship(ship, dt, _orig=orig_tick):
                _orig(ship, dt)
                if ship is ships[0]:
                    victim._cloaking_subsystem = None
                    victim._repair_subsystem = None
            mp.setattr(articulation, "tick_ship", tick_ship)
            game_loop._update_ship_subsystems()
            return before, (cloak._transition_elapsed, sub._condition)

    py_before, python = run(False)
    assert python == py_before          # neither piece ran
    assert run(True) == (py_before, python)


def test_a_row_dropped_mid_walk_is_still_updated():
    """A row freed mid-walk while its ship lives on (native_combat._drop: a
    value the mirror cannot hold) is not skipped: the Python stage still
    runs that ship's remaining pieces, so the native stage hands them back
    too (controller ruling, Task 2 fix round 1). Ship 0's articulation (its
    last piece) drops ship 0's own row and a LATER ship's, whose every
    piece then comes back to Python too; ship 0's, the next tick (no row
    at begin)."""
    from engine.appc.ship_iter import iter_non_rock_ships

    def run(native):
        calls = []
        with pytest.MonkeyPatch.context() as mp:
            _world(mp, native)
            ships = list(iter_non_rock_ships())
            assert all(isinstance(s.__dict__.get("_nslot"), int)
                       for s in ships)
            _spy(mp, calls, pieces=True)
            spied = articulation.tick_ship
            dropped = []

            def tick_ship(ship, dt, _orig=spied):
                _orig(ship, dt)
                if ship is ships[0] and not dropped:
                    for s in (ships[0], ships[2]):
                        nc._drop(s)
                        dropped.append(s.__dict__.get("_nslot"))
            mp.setattr(articulation, "tick_ship", tick_ship)
            for tick in range(2):
                calls.append(("tick", tick, None))
                game_loop._update_ship_subsystems()
            assert dropped == [None, None]      # the rows are gone
            assert native_subsystems.counts()["stages"] == (2 if native
                                                            else 0)
            names = [ships[0].GetName(), ships[2].GetName()]
        return calls, names

    def by_tick(calls):
        out, tick = [], None
        for c in calls:
            if c[0] == "tick":
                tick = c[1]
            else:
                out.append((tick,) + c)
        return out

    python, names = run(False)
    # The dropped ships kept running: power, cloak, repair and
    # articulation, both ticks.
    for name in names:
        kinds = [k for k, n, _ in python if n == name]
        assert kinds.count("power") == kinds.count("repair") == \
            kinds.count("articulation") == 2, (name, kinds)
    native, _ = run(True)
    # Natively, the pieces of rows still live are native: Python runs ship
    # 2's both ticks (its row was gone when the walk reached it) and ship
    # 0's on the second (no row at begin) -- the same calls, in order.
    want = [c for c in by_tick(python)
            if c[1] == "articulation" or c[2] == names[1]
            or (c[2] == names[0] and c[0] == 1)]
    assert by_tick(native) == want
    assert any(c[1] == "repair" for c in want)


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
    watchers; Task 4: the plant's breach, battery watchers and tail; Task 5:
    the cloak's forced decloak and completion, the bay's cannot-complete,
    completion and tail); every kind the native session names has one."""
    events = native_subsystems._EVENTS
    assert set(events) == {"SHIELD_WATCHER", "SHIELD_WATCHER_TAIL", "BREACH",
                           "BATTERY_WATCHER", "POWER_TAIL", "FORCE_DECLOAK",
                           "CLOAK_DONE", "REPAIR_CANNOT", "REPAIR_DONE",
                           "REPAIR_TAIL"}
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
