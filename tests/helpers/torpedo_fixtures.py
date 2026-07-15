"""Shared torpedo-system test fixtures.

Extracted from tests/unit/test_torpedo_spread_volley.py when the Dual/Quad
spread fan was removed (Task 5 of the BC-faithful weapon dispatch branch —
the file's feature died with it, but Task 6/7's launch-fidelity tests reuse
exactly this ship+tube construction).
"""
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


class LiveTarget:
    """A live (never-dead) target at a fixed world location."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(x, y, z)
    def GetWorldLocation(self): return self._loc
    def IsDead(self): return 0


def identity_rotation():
    R = TGMatrix3(); R.MakeIdentity()
    return R


def system_with_tubes(num_tubes, *, target=None, rot=None):
    """Build a TorpedoSystem with `num_tubes` ready PhotonTorpedo tubes on a
    ship at the origin with an (optional) axis-aligned rotation and target
    lock.  Returns (system, ship)."""
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    if rot is not None:
        ship.SetMatrixRotation(rot)
    ship._target = target
    ship._target_subsystem = None

    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent

    for i in range(num_tubes):
        tube = TorpedoTube("Torpedo %d" % i)
        tube._max_ready = 1
        tube._num_ready = 1
        tube._reload_delay = 40.0
        parent.AddChildSubsystem(tube)
    return parent, ship
