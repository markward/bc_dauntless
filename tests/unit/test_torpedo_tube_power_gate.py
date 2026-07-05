"""TorpedoTube.Fire — per-fire power gate.

Each torpedo costs ``GetCurrentAmmoType().GetPowerCost()`` (Photon=20,
Quantum=30, Klingon=40, etc.).  When the firing ship's PowerSubsystem
can't cover the cost via StealPower (main battery only — Task 2), the
launch is a silent no-op: tube stays loaded, no torpedo spawns, no
sound plays.

Task 2 changed StealPower to be main-battery-only (returns float amount
taken).  Tests reflect the new semantics.

Test ships without a bound PowerProperty (the most common Phase-1
fixture: ``ShipClass_Create("Test")`` without a hardpoint) bypass the
gate entirely — keeps the existing torpedo fixtures from regressing
just because a default-construction PowerSubsystem sits there at zero
power.
"""
from unittest.mock import patch

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
    a PowerProperty so the new gate engages.  Returns the loaded tube."""
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(parent_prop)
    ship._torpedo_system = parent
    parent._parent_ship = ship
    # Stamp an ammo type so the per-fire gate can read the cost.
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


def test_fire_succeeds_when_power_covers_cost():
    """StealPower now drains main battery (Task 2); fixture puts power there."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=100.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 0
    assert len(_active) == 1
    # 20-cost photon drained from main battery.
    assert ship.GetPowerSubsystem().GetMainBatteryPower() == 80.0
    _active.clear()


def test_fire_silent_no_op_when_power_insufficient():
    """Main battery empty → StealPower returns 0.0 (falsy) → no fire.

    Tube stays loaded, no torpedo spawned, no fire-time stamped.
    Note: partial steal IS possible (Task 2 semantics) but a 20-unit
    torpedo with only 5 units in main takes only 5 (a partial steal
    which is truthy), so the gate fires.  To test the empty case we
    set main_battery=0 explicitly."""
    _active.clear()
    import math
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=0.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert tube.GetNumReady() == 1
    assert len(_active) == 0
    assert tube.GetLastFireTime() == -math.inf
    # Power untouched (main was already 0).
    assert ship.GetPowerSubsystem().GetMainBatteryPower() == 0.0
    _active.clear()


def test_fire_falls_through_to_main_battery():
    """Main battery has plenty → fires and drains main (unchanged path)."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, available=0.0, main_battery=1000.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    assert ship.GetPowerSubsystem().GetMainBatteryPower() == 980.0
    _active.clear()


def test_fire_without_power_property_bypasses_gate():
    """Test fixture without a PowerProperty bound (common Phase-1 case)
    must not trip the gate — keeps unrelated tests from regressing on
    a stub PowerSubsystem at zero power."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, with_power_property=False)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    _active.clear()


def test_fire_without_power_subsystem_bypasses_gate():
    """A ship whose PowerSubsystem was scrubbed (no hardpoint registered
    a PowerProperty) still fires — gate only applies when the ship has
    a power plant."""
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_galaxy_like_torp(ship, with_power_property=False)
    ship._power_subsystem = None
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)
    assert len(_active) == 1
    _active.clear()
