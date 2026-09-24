"""Splash damage must reach a subsystem where its part has CARRIED it.

apply_hit's catchment centre came from a private copy of the mount formula
(combat._subsystem_world_position) that never learned about articulation,
while the hit point comes off the POSED hull. With a Bird of Prey's wings up,
a wingtip cannon sits ~0.9 ship units from its rest mount against a ~0.4 GU
catchment: a direct hit on the drawn gun reached nothing, and a hit on the
empty space where the gun would be wings-down damaged it.

The catchment centre must be what subsystems.subsystem_world_position returns
-- the same point the SPV pins and the weapon fire origin use.
"""
import pytest

from engine.appc import articulation
from engine.appc.combat import apply_hit
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.subsystems import subsystem_world_position
import App

STAR_CANNON = (1.008, 0.450, -0.670)   # BoP starboard wingtip, rest pose


class _Sub:
    def __init__(self, name, pos, radius):
        self.name = name
        self._pos = TGPoint3(*pos)
        self._radius = radius
        self._condition = 1000.0

    def GetPosition(self):      return self._pos
    def GetRadius(self):        return self._radius
    def GetCondition(self):     return self._condition
    def GetMaxCondition(self):  return 1000.0
    def IsDamaged(self):        return self._condition < 1000.0
    def IsDisabled(self):       return False
    def IsDestroyed(self):      return False


class _Ship(App.TGEventHandlerObject):
    """A Bird of Prey with both wings at their authored cruise angle."""

    def __init__(self, subs, wings_up=True):
        super().__init__()
        self._hull = subs[0]
        self._subs = list(subs)
        self._articulation_leaf = "birdofprey"
        self._articulation_angles = {
            p.GetName(): (p.angle_for("cruise") if wings_up else 0.0)
            for p in articulation.rig_for("birdofprey")
        }
        self.damaged = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()
    def GetShields(self):       return None

    def DamageSystem(self, sub, amount, source=None):
        self.damaged.append(sub.name)


def _ship(wings_up=True):
    hull = _Sub("Hull", (0.0, 0.0, 0.0), 1.0)
    cannon = _Sub("Star Cannon", STAR_CANNON, 0.1)
    return _Ship([hull, cannon], wings_up=wings_up), cannon


def _hit(ship, point):
    apply_hit(ship, damage=100.0, hit_point=TGPoint3(*point), source=None,
              splash_radius=0.05)
    return "Star Cannon" in ship.damaged


def test_the_fixture_actually_moves_the_cannon():
    """Guard: if the rig stopped resolving, both tests below would be
    testing a stationary mount and prove nothing."""
    ship, cannon = _ship()
    w = subsystem_world_position(cannon, ship)
    moved = ((w.x - STAR_CANNON[0]) ** 2 + (w.y - STAR_CANNON[1]) ** 2
             + (w.z - STAR_CANNON[2]) ** 2) ** 0.5
    assert moved > 0.5


def test_a_hit_on_the_DRAWN_wingtip_cannon_damages_it():
    ship, cannon = _ship()
    w = subsystem_world_position(cannon, ship)
    assert _hit(ship, (w.x, w.y, w.z)), (
        "a direct hit on the cannon where it is drawn must reach it")


def test_a_hit_where_the_cannon_WOULD_be_at_rest_misses_it():
    """With the wings up that point is empty space."""
    ship, _cannon = _ship()
    assert not _hit(ship, STAR_CANNON)


def test_wings_down_the_rest_mount_is_still_the_catchment():
    """At angle 0 articulation is identity -- the unarticulated path must be
    unchanged."""
    ship, _cannon = _ship(wings_up=False)
    assert _hit(ship, STAR_CANNON)
