"""The native power piece (phase 6 A1, Task 4; subsystem_step.h THE POWER
PIECE): ``PowerSubsystem.Update`` with its consumer pump run natively by the
subsystem stage, bit for bit, its breach and battery-watcher crossings
handed back to Python as EVENT records.

The per-tick state differential against the Python stage is
tests/integration/test_native_subsystems_differential.py; these pin the
pieces of the contract one at a time, each against the Python stage
(``DAUNTLESS_NATIVE_SUBSYSTEMS=0``) on the same scene.
"""
import random

import App
import pytest

from engine.appc import death_check, properties
from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.appc.ship_iter import iter_non_rock_ships
from engine.appc.subsystems import PSM_BACKUP_ONLY
from engine.core import loop as game_loop
from tests.helpers import bc_assets, headless_mission

SHIPS = 3               # the player and two combat ships
PIECES_IN_PYTHON = 3    # cloak, repair, articulation (Tasks 5-6)
_PLANT = ("_available_power", "_main_battery_power", "_backup_battery_power",
          "_main_conduit_current", "_backup_conduit_current",
          "_interval_elapsed", "_power_dispensed", "_power_wanted_total",
          "_breach_fired")
_CONSUMER = ("_power_wanted", "_power_received", "_efficiency",
             "_power_factor")


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
    ships = list(iter_non_rock_ships())
    assert len(ships) == SHIPS
    return ships


def _tick(n=1):
    for _ in range(n):
        App.g_kTimerManager._time += game_loop.TICK_DELTA
        game_loop._update_ship_subsystems()


def _hex(v):
    return float(v).hex() if isinstance(v, float) else v


def _state(ships):
    """Every field the power piece writes, floats by hex."""
    rows = []
    for ship in ships:
        plant = ship.GetPowerSubsystem()
        d = plant.__dict__
        rows.append([_hex(d[n]) for n in _PLANT]
                    + [_hex(plant._main_battery_watcher._value),
                       _hex(plant._backup_battery_watcher._value)])
        for c in ship._powered_consumers:
            rows.append([type(c).__name__]
                        + [_hex(c.__dict__[n]) for n in _CONSUMER]
                        + [_hex(c.__dict__.get("_backup_reserve"))])
    return rows


def _power_records_python(counts, stages):
    """How many POWER pieces ran as RUN_PYTHON records: the other Python
    pieces are one record each per ship per stage."""
    return counts["run_python"] - PIECES_IN_PYTHON * SHIPS * stages


def test_sdk_set_main_battery_power_reaches_the_native_step():
    """Review Focus 2: an SDK ``SetMainBatteryPower`` (DockWithStarbase,
    ShipScriptActions) is what the next native pump and recharge start
    from -- the setter pushes -- bit for bit what the Python stage does."""
    def run(native):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            native_subsystems.reset_counts()
            plant = ships[1].GetPowerSubsystem()
            _tick(20)
            # The SDK's own call (DockWithStarbase.py: pPower.Set...).
            plant.SetMainBatteryPower(123.0)
            _tick(1)
            after_one = plant._main_battery_power
            _tick(79)           # past the next interval
            return _state(ships), after_one, native_subsystems.counts()

    python, py_one, _ = run(False)
    native, na_one, counts = run(True)
    assert native == python
    assert na_one == py_one and na_one <= 123.0
    assert counts["stages"] == 100
    assert _power_records_python(counts, 100) == 0, counts


def test_template_set_power_output_pushes_to_every_ship_using_it():
    """Review Focus 2: a mission changing a SHARED PowerProperty template at
    runtime (one per ship class) changes every plant using it on the next
    interval: the setter pushes the template's one mirror row, which every
    plant's `_property` names."""
    def run(native):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            a, b = (s.GetPowerSubsystem() for s in ships[1:])
            prop = a.GetProperty()
            b.SetProperty(prop)             # the two now share a template
            for plant in (a, b):
                plant.SetMainBatteryPower(0.0)
                plant.SetBackupBatteryPower(0.0)
            native_subsystems.reset_counts()
            prop.SetPowerOutput(7.0)        # the template, once
            prop.SetBackupBatteryLimit(prop.GetBackupBatteryLimit())
            _tick(120)
            row = (nc._h.combat_dump(prop.__dict__["_nslot"])
                   if native else None)
            return (_state(ships), [p._backup_battery_power for p in (a, b)],
                    row, native_subsystems.counts())

    python, py_backup, _, _ = run(False)
    native, na_backup, row, counts = run(True)
    assert native == python
    assert row["PowerOutput"] == 7.0 and row["power_props_ok"] == 1
    # Both plants recharged at the template's new output (7/s is far below
    # every consumer's draw, so the main battery is spent; what spills is
    # the same for both).
    assert na_backup == py_backup
    assert _power_records_python(counts, 120) == 0, counts


def test_a_battery_crossing_fires_mid_stage_through_the_watchers_own_update():
    """A ConditionPowerBelow-style range check on the main battery watcher:
    the native piece stops at that watcher, Python's `_update` fires the SDK
    event with the value the Python piece would have computed, the handler's
    write is seen by the walk after it."""
    def run(native):
        fired = []
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            plant = ships[0].GetPowerSubsystem()
            watcher = plant.GetMainBatteryWatcher()
            et = App.Game_GetNextEventType()
            evt = App.TGFloatEvent_Create()
            evt.SetEventType(et)
            evt.SetSource(plant)
            watcher.AddRangeCheck(0.5, App.FloatRangeWatcher.FRW_BOTH, evt)
            mgr = App.g_kEventManager
            orig = mgr.AddEvent

            def add_event(e, _orig=orig):
                if e.GetEventType() == et:
                    fired.append(float(e.GetFloat()).hex())
                    # A handler's write to the NEXT ship's plant.
                    nxt = ships[1].GetPowerSubsystem()
                    nxt.SetMainBatteryPower(nxt.GetMainBatteryPower() * 0.5)
                return _orig(e)
            mp.setattr(mgr, "AddEvent", add_event)
            native_subsystems.reset_counts()
            _tick(5)
            plant.SetMainBatteryPower(plant.GetMainBatteryLimit() * 0.5001)
            _tick(60)
            return fired, _state(ships), native_subsystems.counts()

    py_fired, python, _ = run(False)
    na_fired, native, counts = run(True)
    assert py_fired, "the scene never crossed"
    assert na_fired == py_fired
    assert native == python
    assert counts["events"] >= len(na_fired)
    assert _power_records_python(counts, 65) == 0, counts


def test_a_breach_runs_trigger_breach_once():
    """A destroyed plant: the native piece latches ``_breach_fired`` and the
    BREACH record runs ``_trigger_breach`` (death_check.note_breach), once,
    in the walk where the Python stage runs it."""
    def run(native):
        noted = []
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            orig = death_check.note_breach

            def note_breach(ship, plant, _orig=orig):
                noted.append((ship.GetName(), plant.GetName()))
                return _orig(ship, plant)
            mp.setattr(death_check, "note_breach", note_breach)
            plant = ships[2].GetPowerSubsystem()
            _tick(3)
            plant.SetCondition(0.0)
            _tick(5)
            return noted, _state(ships), native_subsystems.counts()

    py_noted, python, _ = run(False)
    na_noted, native, counts = run(True)
    assert len(py_noted) == 1
    assert na_noted == py_noted
    assert native == python
    assert _power_records_python(counts, 8) == 0, counts


def test_an_instance_power_mode_reaches_the_native_step():
    """POWER_MODE (and the other class constants the pump reads) may be
    overridden per instance: the write pushes (NativeClassDefault), so the
    native draw takes the instance's mode, as the Python one does."""
    def run(native):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, native)
            native_subsystems.reset_counts()
            _tick(10)
            sensors = ships[1].GetSensorSubsystem()
            sensors.POWER_MODE = PSM_BACKUP_ONLY
            _tick(70)
            return _state(ships), native_subsystems.counts()

    python, _ = run(False)
    native, counts = run(True)
    assert native == python
    assert _power_records_python(counts, 80) == 0, counts


def test_python_pieces_hands_every_power_piece_to_python():
    """The test-facing hook: with POWER in python_pieces every plant's
    Update is Python's, and the state is the native run's, bit for bit."""
    def run(hooked):
        with pytest.MonkeyPatch.context() as mp:
            ships = _world(mp, True)
            native_subsystems.python_pieces = (
                1 << native_subsystems.POWER) if hooked else 0
            native_subsystems.reset_counts()
            _tick(70)
            return _state(ships), native_subsystems.counts()

    native, _ = run(False)
    hooked, counts = run(True)
    assert hooked == native
    assert _power_records_python(counts, 70) == SHIPS * 70, counts


def test_the_mirror_agrees_after_native_pumps():
    """The audit: every power field the native piece wrote back is what the
    mirror holds (no row keeps a write Python never got, or misses one)."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp, True)
        _tick(70)
        ships[1].GetPowerSubsystem().GetMainBatteryWatcher().AddRangeCheck(
            0.25, App.FloatRangeWatcher.FRW_BELOW, App.TGFloatEvent_Create())
        _tick(5)
        nc._failures.clear()
        nc.audit_mirror()
        assert nc._failures == []


def test_the_mirrored_property_fields_are_twins():
    """properties.py spells the pushing setters' fields so a setter needs no
    import: the same set native_combat mirrors."""
    assert properties._MIRRORED_FIELDS == nc.MIRRORED_PROPERTY_FIELDS
