"""The native power piece (phase 6 A1, Task 4; subsystem_step.h THE POWER
PIECE): the power plant's tick with its consumer pump, native only since
Task 8 (there is no Python copy), its breach and battery-watcher crossings
handed back to Python as EVENT records. The goldens pin it bit for bit;
these pin the pieces of the contract one at a time.
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


def _no_skips():
    """Every piece ran: none was skipped (subsystem_step.h THE SKIPS)."""
    assert native_subsystems.skip_counts() == {}


def test_sdk_set_main_battery_power_reaches_the_native_step():
    """Review Focus 2: an SDK ``SetMainBatteryPower`` (DockWithStarbase,
    ShipScriptActions) is what the next native pump and recharge start
    from -- the setter pushes."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        native_subsystems.reset_counts()
        plant = ships[1].GetPowerSubsystem()
        _tick(20)
        # The SDK's own call (DockWithStarbase.py: pPower.Set...).
        plant.SetMainBatteryPower(123.0)
        _tick(1)
        after_one = plant._main_battery_power
        row = nc._h.combat_dump(plant.__dict__["_nslot"])
        _tick(79)           # past the next interval
        counts = native_subsystems.counts()
    # The pump drew from the 123 the SDK set (not from the old battery).
    assert 0.0 <= after_one <= 123.0
    assert row["_main_battery_power"] == after_one
    assert counts["stages"] == 100
    _no_skips()


def test_template_set_power_output_pushes_to_every_ship_using_it():
    """Review Focus 2: a mission changing a SHARED PowerProperty template at
    runtime (one per ship class) changes every plant using it on the next
    interval: the setter pushes the template's one mirror row, which every
    plant's `_property` names."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        a, b = (s.GetPowerSubsystem() for s in ships[1:])
        prop = a.GetProperty()
        b.SetProperty(prop)             # the two now share a template
        for plant in (a, b):
            plant.SetMainBatteryPower(0.0)
            plant.SetBackupBatteryPower(0.0)
            plant._interval_elapsed = 0.0
        native_subsystems.reset_counts()
        prop.SetPowerOutput(7.0)        # the template, once
        _tick(61)                       # one interval (61 x 1/60 >= 1.0)
        row = nc._h.combat_dump(prop.__dict__["_nslot"])
        elapsed = 0.0
        for _ in range(61):
            elapsed = elapsed + game_loop.TICK_DELTA
            if elapsed >= 1.0:
                break
        dispensed = [p.GetPowerDispensed() for p in (a, b)]
        batteries = [p._main_battery_power + p._backup_battery_power
                     for p in (a, b)]
    assert row["PowerOutput"] == 7.0 and row["power_props_ok"] == 1
    # Each plant recharged 7/s x its condition x the interval (full health
    # here) and nothing more: what it holds plus what it dispensed since.
    for held, out in zip(batteries, dispensed):
        assert 0.0 < held + out <= 7.0 * elapsed + 1e-9
    _no_skips()


def test_a_battery_crossing_fires_mid_stage_through_the_watchers_own_update():
    """A ConditionPowerBelow-style range check on the main battery watcher:
    the native piece stops at that watcher, Python's `_update` fires the SDK
    event with the value the piece computed, and the handler's write to the
    NEXT ship is what that ship's pump then reads."""
    fired = []
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        plant = ships[0].GetPowerSubsystem()
        watcher = plant.GetMainBatteryWatcher()
        et = App.Game_GetNextEventType()
        evt = App.TGFloatEvent_Create()
        evt.SetEventType(et)
        evt.SetSource(plant)
        watcher.AddRangeCheck(0.5, App.FloatRangeWatcher.FRW_BOTH, evt)
        mgr = App.g_kEventManager
        orig = mgr.AddEvent
        nxt = ships[1].GetPowerSubsystem()
        seen = []

        def add_event(e, _orig=orig):
            if e.GetEventType() == et:
                fired.append(e.GetFloat())
                # A handler's write to the NEXT ship's plant.
                nxt.SetMainBatteryPower(1000.0)
                seen.append(nxt._main_battery_power)
            return _orig(e)
        mp.setattr(mgr, "AddEvent", add_event)
        native_subsystems.reset_counts()
        _tick(5)
        plant.SetMainBatteryPower(plant.GetMainBatteryLimit() * 0.5001)
        _tick(60)
        counts = native_subsystems.counts()
    assert fired, "the scene never crossed"
    # Each crossing carried a battery fraction, through 0.5.
    assert all(0.0 <= v <= 1.0 for v in fired), fired
    assert seen and all(v == 1000.0 for v in seen)
    assert counts["events"] >= len(fired)
    _no_skips()


def test_a_breach_runs_trigger_breach_once():
    """A destroyed plant: the native piece latches ``_breach_fired`` and the
    BREACH record runs ``_trigger_breach`` (death_check.note_breach), once."""
    noted = []
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
        orig = death_check.note_breach

        def note_breach(ship, plant, _orig=orig):
            noted.append((ship.GetName(), plant.GetName()))
            return _orig(ship, plant)
        mp.setattr(death_check, "note_breach", note_breach)
        plant = ships[2].GetPowerSubsystem()
        _tick(3)
        plant.SetCondition(0.0)
        _tick(5)
    assert noted == [(ships[2].GetName(), plant.GetName())]
    assert plant._breach_fired is True
    _no_skips()


def test_an_instance_power_mode_reaches_the_native_step():
    """POWER_MODE (and the other class constants the pump reads) may be
    overridden per instance: the write pushes (NativeClassDefault), so the
    native draw takes the instance's mode -- a backup-only consumer never
    touches the main battery or its conduit. Alone on its ship (the other
    consumers off or free), its draw shows as the backup's whole movement
    and none of the main's."""
    from engine.appc.properties import PowerProperty
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import PowerSubsystem, SensorSubsystem
    from tests.helpers.subsystem_stage import tick_subsystems
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    ship = ShipClass()
    ship.SetName("Backup Only")
    plant = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(0.0)                # no recharge: pure draws
    prop.SetMainBatteryLimit(10000.0)
    prop.SetBackupBatteryLimit(10000.0)
    prop.SetMainConduitCapacity(1000.0)
    prop.SetBackupConduitCapacity(1000.0)
    plant.SetProperty(prop)
    plant.SetMainBatteryPower(5000.0)
    plant.SetBackupBatteryPower(5000.0)
    ship.SetPowerSubsystem(plant)
    sensors = SensorSubsystem("Sensors")
    sensors.SetNormalPowerPerSecond(60.0)
    sensors.TurnOn()
    ship.SetSensorSubsystem(sensors)
    sensors.POWER_MODE = PSM_BACKUP_ONLY
    row = nc._h.combat_dump(sensors.__dict__["_nslot"])
    assert row["POWER_MODE"] == PSM_BACKUP_ONLY
    tick_subsystems([ship], game_loop.TICK_DELTA, ticks=60)   # budgets seeded
    main0, main_conduit0 = (plant._main_battery_power,
                            plant._main_conduit_current)
    backup0 = plant._backup_battery_power
    for _ in range(70):
        tick_subsystems([ship], game_loop.TICK_DELTA)
        assert plant._main_battery_power == main0
        assert plant._main_conduit_current == main_conduit0
    assert plant._backup_battery_power < backup0     # it drew from backup
    assert sensors.GetPowerPercentage() > 0.0
    _no_skips()


def test_the_mirror_agrees_after_native_pumps():
    """The audit: every power field the native piece wrote back is what the
    mirror holds (no row keeps a write Python never got, or misses one)."""
    with pytest.MonkeyPatch.context() as mp:
        ships = _world(mp)
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
