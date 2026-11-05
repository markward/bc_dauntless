"""The native subsystem stage's driver (phase 6 A1; engine/appc/
native_subsystems.py): the shield, power, cloak and repair pieces are
native only (Task 8), articulation is handed back as one RUN_PYTHON record
per rigged ship, and a piece the mirror cannot run is skipped, counted and
logged once (subsystem_step.h THE SKIPS; rulings R8-1, R8-2).
"""
import random

import App
import pytest

from engine.appc import articulation
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.core import loop as game_loop
from engine.appc import articulated_part
from tests.helpers import bc_assets, headless_mission
from tests.helpers.rig_all_ships import rig_all_ships

TICKS = 40      # past the first shield charge (tick 30 or 31)


@pytest.fixture(autouse=True)
def _clean():
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    nc.reset()
    yield
    nc.reset()
    articulated_part.reset()


def _world(mp, audit=False):
    mp.setenv("DAUNTLESS_COMBAT_SHIPS", "2")
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    env = {"DAUNTLESS_NATIVE_COMBAT": "1"}
    if audit:
        env["DAUNTLESS_NATIVE_AUDIT"] = "1"
    nc.configure(env)
    # Every ship rigged: its ARTICULATION piece is Python's every tick (a
    # rigless ship's is skipped natively: test_native_subsystems_
    # articulation.py).
    rig_all_ships()


def _spy(mp, calls):
    """Every Python call of the stage: articulation.tick_ship, logged
    (ship name, dt) and then run."""
    orig_tick = articulation.tick_ship

    def tick_ship(ship, dt, _orig=orig_tick):
        calls.append(("articulation", ship.GetName(), dt))
        return _orig(ship, dt)
    mp.setattr(articulation, "tick_ship", tick_ship)


def test_only_articulation_comes_back_to_python():
    """Every shield, power, cloak and repair piece is native: one record
    (articulation's) per rigged ship per stage, in roster order, and no
    skip."""
    from engine.appc.ship_iter import iter_non_rock_ships
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        _world(mp)
        names = [s.GetName() for s in iter_non_rock_ships()]
        _spy(mp, calls)
        native_subsystems.reset_counts()
        for _ in range(TICKS):
            App.g_kTimerManager._time += game_loop.TICK_DELTA
            game_loop._update_ship_subsystems()
        counts = native_subsystems.counts()
    assert len(names) == 3, names
    assert counts["stages"] == TICKS, counts
    assert counts["run_python"] == 3 * TICKS, counts
    assert calls == [("articulation", n, game_loop.TICK_DELTA)
                     for _ in range(TICKS) for n in names]
    assert native_subsystems.skip_counts() == {}


def test_a_ship_that_loses_a_subsystem_mid_walk(monkeypatch):
    """A handler that detaches a LATER piece removes that piece: the native
    walk reads the ship's ref when it gets there (the detach pushed it).
    Here the first ship's articulation detaches the next ship's cloak and
    bay while the cloak is mid-transition and the bay has work: neither
    moves that tick, and nothing is skipped (a None ref is no call)."""
    from engine.appc.ship_iter import iter_non_rock_ships
    with pytest.MonkeyPatch.context() as mp:
        _world(mp)
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
        after = (cloak._transition_elapsed, sub._condition)
    assert before[0] > 0.0          # the cloak was moving
    assert after == before          # neither piece ran
    assert native_subsystems.skip_counts() == {}


def test_a_row_dropped_mid_walk_skips_its_pieces(capsys):
    """Ruling R8-2: a row freed mid-walk while its ship lives on
    (native_combat._drop: a value the mirror cannot hold) has no Python
    stage to go to: its remaining shield, power, cloak and repair pieces
    are SKIPPED, counted and logged once; its articulation, whose Python is
    kept, still runs. Ship 0's articulation (its last piece) drops ship 0's
    own row and a LATER ship's: ship 2 is skipped as LOST_ROW that tick,
    and both as NO_ROW the next."""
    from engine.appc.ship_iter import iter_non_rock_ships
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        _world(mp)
        ships = list(iter_non_rock_ships())
        assert all(isinstance(s.__dict__.get("_nslot"), int) for s in ships)
        _spy(mp, calls)
        spied = articulation.tick_ship
        dropped = []

        def tick_ship(ship, dt, _orig=spied):
            _orig(ship, dt)
            if ship is ships[0] and not dropped:
                for s in (ships[0], ships[2]):
                    nc._drop(s)
                    dropped.append(s.__dict__.get("_nslot"))
        mp.setattr(articulation, "tick_ship", tick_ship)
        native_subsystems.reset_counts()
        for _ in range(2):
            game_loop._update_ship_subsystems()
        skips = native_subsystems.skip_counts()
    assert dropped == [None, None]      # the rows are gone
    four = ("SHIELD", "POWER", "CLOAK", "REPAIR")
    # Ship 2's four pieces on tick 0 (LOST_ROW); ships 0 and 2 on tick 1
    # (NO_ROW). A piece the ship lacks entirely (no cloak) is still one
    # skip: the ship's row is what the session could not read.
    assert skips == dict([((p, "LOST_ROW"), 1) for p in four]
                         + [((p, "NO_ROW"), 2) for p in four]), skips
    # Articulation still ran for every ship on both ticks.
    assert len(calls) == 2 * len(ships)
    err = capsys.readouterr().err
    for p in four:
        for why in ("LOST_ROW", "NO_ROW"):
            assert err.count("skip %s)" % why) >= 1
    # Logged ONCE per (piece, reason), however often it recurs -- and the
    # line says the freeze lasts: a ship without its row is never run again.
    assert err.count("SHIELD skipped") == 2, err
    for line in err.splitlines():
        if "skip NO_ROW" in line or "skip LOST_ROW" in line:
            assert "persists" in line, line


def test_a_skip_is_an_audit_failure():
    """Under DAUNTLESS_NATIVE_AUDIT=1 every skip is an audit failure (ruling
    R8-1): a generator whose row was dropped reads unrepresentable from its
    ship (a REF skip) and from the plant's consumer list (the whole plant
    is a CONSUMER skip), and the stage never calls a Python copy for
    either."""
    from engine.appc.ship_iter import iter_non_rock_ships
    with pytest.MonkeyPatch.context() as mp:
        _world(mp, audit=True)
        ship = list(iter_non_rock_ships())[1]
        gen = ship.GetShields()
        nc._drop(gen)
        nc._failures.clear()
        native_subsystems.reset_counts()
        game_loop._update_ship_subsystems()
        failures = list(nc._failures)
        skips = native_subsystems.skip_counts()
    assert skips == {("SHIELD", "REF"): 1, ("POWER", "CONSUMER"): 1}, skips
    assert ("subsystem stage", "skip SHIELD REF") in failures, failures
    assert ("subsystem stage", "skip POWER CONSUMER") in failures, failures


def test_the_event_table_holds_the_native_pieces_events():
    """Each native piece's event kinds have a handler (Task 3: the shield
    watchers; Task 4: the plant's breach, battery watchers and tail; Task 5:
    the cloak's forced decloak and completion, the bay's cannot-complete,
    completion and per-item hand-over); every kind the native session names
    has one."""
    events = native_subsystems._EVENTS
    assert set(events) == {"SHIELD_WATCHER", "SHIELD_WATCHER_TAIL", "BREACH",
                           "BATTERY_WATCHER", "POWER_TAIL", "FORCE_DECLOAK",
                           "CLOAK_DONE", "REPAIR_CANNOT", "REPAIR_DONE",
                           "REPAIR_SET"}
    assert set(native_subsystems._EVENT_HANDLERS) == set(events.values())


@pytest.mark.parametrize("target", [
    "engine.appc.ship_iter.iter_ships",
    "engine.appc.ship_iter.iter_non_rock_ships",
    "engine.appc.ship_iter.iter_set_objects"])
def test_a_patched_roster_raises(monkeypatch, target):
    """Ruling R8-5 (A4): the driver walks the sets itself, so a roster a
    caller patched (a test feeding the stage its own ships) would be
    ignored -- the stage raises instead of silently running none of them.
    tests/helpers/subsystem_stage.py is how a test ticks its own ships."""
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    native_subsystems.reset_counts()
    monkeypatch.setattr(target, lambda *a, **k: iter(()))
    with pytest.raises(RuntimeError, match="roster .* is patched"):
        game_loop._update_ship_subsystems()
    assert native_subsystems.counts()["stages"] == 0
    monkeypatch.undo()
    game_loop._update_ship_subsystems()         # stock again: runs
    assert native_subsystems.counts()["stages"] == 1
