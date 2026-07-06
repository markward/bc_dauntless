"""TorpedoTube.Fire — power model after Task 4b (IOU closed by Task 8).

Task 4b decision: BC has no per-shot battery debit.  Weapon energy cost is the
continuous NormalPowerPerSecond consumer draw (landed in Task 4).  Charge/reload
rates are the gameplay gate — scaled by power factor (Task 8, now landed).

Task 8 closed the transitional gap: a fully-unpowered ship (factor 0) can still
fire an already-loaded tube (BC-faithful — a chambered torpedo launches), but
it cannot RELOAD unpowered (UpdateReload returns early at factor <= 0).

The per-shot debit path (_debit_ship_power / _debit_power) was removed in Task
4b.  These tests confirm:
  - Fire succeeds when tubes are loaded, regardless of battery level.
  - The main battery level is NOT changed by a torpedo fire.
  - Fire is still gated on tube charge/reload state and system power state.
"""
from unittest.mock import patch
import math

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.properties import (
    WeaponSystemProperty, PowerProperty,
)
from engine.appc.projectiles import _active


def _wire_galaxy_like_torp(ship, *, with_power_property=True,
                            available=0.0, main_battery=0.0):
    """Build a Photon-armed TorpedoSystem on ``ship`` and optionally bind
    a PowerProperty so the consumer-draw model is active.  Returns the
    loaded tube."""
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(parent_prop)
    ship._torpedo_system = parent
    parent._parent_ship = ship
    # Stamp an ammo type so the (now-removed) per-fire gate had a cost to read.
    from engine.appc.subsystems import TorpedoAmmoType
    parent.AddAmmoType(TorpedoAmmoType("Photon", launch_speed=19.0, power_cost=20.0))
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    parent.AddChildSubsystem(tube)

    if with_power_property:
        ps = ship.GetPowerSubsystem()
        prop = PowerProperty("WarpCore")
        prop.SetPowerOutput(1000.0)
        prop.SetMainBatteryLimit(250000.0)
        ps.SetProperty(prop)
        ps.SetAvailablePower(available)
        ps.SetMainBatteryPower(main_battery)
    return tube


def test_fire_does_not_debit_battery_per_shot():
    """With nearly-empty main battery, firing a loaded torpedo does NOT
    change the battery level and the shot SUCCEEDS (no per-shot drain).

    This is the inverse of the old test_partial_steal_fires_interim_until_task4
    — the per-shot debit path has been removed (Task 4b).
    """
    _active.clear()
    ship = ShipClass_Create("Test")
    # Battery well below the old 20-unit photon cost
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=5.0)
    battery_before = ship.GetPowerSubsystem().GetMainBatteryPower()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    # Shot fired (tube was loaded)
    assert len(_active) == 1
    # Battery NOT changed by the fire
    assert ship.GetPowerSubsystem().GetMainBatteryPower() == battery_before
    _active.clear()


def test_fire_succeeds_loaded_tube_any_battery():
    """A loaded tube fires regardless of main battery level — gate is
    charge/reload state only, not power level."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=0.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0
    assert len(_active) == 1
    _active.clear()


def test_fire_leaves_battery_untouched():
    """Battery stays at its pre-fire value after a successful shot."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=100.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    assert ship.GetPowerSubsystem().GetMainBatteryPower() == 100.0
    _active.clear()


def test_fire_blocked_when_tube_unloaded():
    """Tube must not fire when num_ready == 0 — reload gate unchanged."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=1000.0)
    tube._num_ready = 0
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 0
    _active.clear()


def test_fire_blocked_when_system_off():
    """TorpedoSystem turned off → CanFire returns 0 → no fire."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=1000.0)
    tube.GetParentSubsystem().TurnOff()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 0
    _active.clear()


def test_fire_without_power_property_still_works():
    """Test fixture without a PowerProperty bound fires normally —
    no power plant means no consumer-draw gate either."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, with_power_property=False)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    _active.clear()


def test_fire_without_power_subsystem_bypasses_gate():
    """A ship whose PowerSubsystem was scrubbed still fires — gate only
    applies when the ship has a power plant."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, with_power_property=False)
    ship._power_subsystem = None
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    _active.clear()
