"""TorpedoTube.CanFire — audited gate 2 (spec §3.3): "subsystem not
disabled". A tube damaged below its DisabledPercentage threshold must not
be able to fire, even though it is loaded, off-cooldown, and its parent
TorpedoSystem is powered on.
"""
from unittest.mock import patch

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.properties import WeaponSystemProperty
from engine.appc.projectiles import _active


def _wire_loaded_tube(ship):
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(parent_prop)
    ship._torpedo_system = parent
    parent._parent_ship = ship
    from engine.appc.subsystems import TorpedoAmmoType
    parent.AddAmmoType(TorpedoAmmoType("Photon", launch_speed=19.0, power_cost=20.0))
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    tube.SetMaxCondition(100.0)
    tube.SetCondition(100.0)
    tube.SetDisabledPercentage(0.25)
    parent.AddChildSubsystem(tube)
    return tube


def test_disabled_tube_cannot_fire():
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_loaded_tube(ship)
    # Damage below the 25% threshold: disabled.
    tube.SetCondition(10.0)
    assert tube.IsDisabled() == 1

    assert tube.CanFire() == 0
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        fired = tube.Fire(target=None, offset=None)
    assert fired is False
    assert len(_active) == 0
    _active.clear()


def test_healthy_tube_still_fires():
    _active.clear()
    ship = ShipClass_Create("Test")
    tube = _wire_loaded_tube(ship)
    assert tube.IsDisabled() == 0

    assert tube.CanFire() == 1
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        fired = tube.Fire(target=None, offset=None)
    assert fired is True
    assert len(_active) == 1
    _active.clear()
