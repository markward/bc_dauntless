"""TorpedoTube.Fire — the dumb-fire path (target=None) must clear any
stale _target lock left by a previous targeted shot.

Reachable in-game: player fires targeted (stamps tube._target), deselects
the target, then taps fire again (target=None). Without clearing, the new
torpedo's homing lookup in _spawn_projectile (``getattr(emitter, "_target",
None)``) would read the STALE lock and home on a target the player no
longer has selected.
"""
from unittest.mock import patch

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.properties import WeaponSystemProperty
from engine.appc.projectiles import _active


class _Target:
    def GetWorldLocation(self): return TGPoint3(0.0, 100.0, 0.0)
    def IsDead(self): return 0


def _galaxy_tube_with_photon_script(num_ready=2, max_ready=2):
    ship = ShipClass_Create("Test")
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(parent_prop)
    ship._torpedo_system = parent
    parent._parent_ship = ship
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = max_ready
    tube._num_ready = num_ready
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.0
    parent.AddChildSubsystem(tube)
    return tube, parent, ship


def _clear_gates(tube, parent):
    """Bypass the ship-wide stagger + per-tube ImmediateDelay gates so a
    second Fire() call in the same test tick succeeds deterministically,
    without depending on real game-clock advancement."""
    tube._last_fire_time = -1000.0
    parent._last_system_fire_time = -1000.0


def test_dumb_fire_after_targeted_fire_clears_stale_lock():
    _active.clear()
    tube, parent, ship = _galaxy_tube_with_photon_script()
    target = _Target()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        assert tube.Fire(target=target, offset=None) is True
    first = _active[-1]
    assert first._target_ship is target
    assert tube._target is target

    _clear_gates(tube, parent)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        assert tube.Fire(target=None, offset=None) is True
    second = _active[-1]
    assert second is not first
    assert second._target_ship is None
    assert tube._target is None
    _active.clear()
