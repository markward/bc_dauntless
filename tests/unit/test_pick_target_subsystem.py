"""pick_target_subsystem walks the ship's subsystem tree; returns the
subsystem whose hardpoint position is closest to hit_point AND within
~2× its radius.  Falls back to hull when no subsystem matches.
"""
from engine.appc.math import TGPoint3
from engine.appc.combat import pick_target_subsystem


class _FakeSubsystem:
    def __init__(self, name, position, radius):
        self._name = name
        self._position = position
        self._radius = radius

    def GetName(self): return self._name
    def GetPosition(self): return self._position
    def GetRadius(self): return self._radius


class _FakeShip:
    def __init__(self, hull=None, children=()):
        self._hull = hull
        self._children = list(children)
        self._loc = TGPoint3(0, 0, 0)

    def GetHull(self): return self._hull
    def GetWorldLocation(self): return self._loc
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i): return self._children[i]


def test_picks_nearest_subsystem_within_radius():
    hull = _FakeSubsystem("Hull", TGPoint3(0, 0, 0), 5.0)
    bridge = _FakeSubsystem("Bridge", TGPoint3(0, 5, 0), 1.0)
    engines = _FakeSubsystem("Engines", TGPoint3(0, -5, 0), 1.0)
    ship = _FakeShip(hull=hull, children=[bridge, engines])
    picked = pick_target_subsystem(ship, TGPoint3(0, 5.5, 0))
    assert picked is bridge


def test_falls_back_to_hull_when_no_subsystem_close():
    hull = _FakeSubsystem("Hull", TGPoint3(0, 0, 0), 5.0)
    bridge = _FakeSubsystem("Bridge", TGPoint3(0, 5, 0), 1.0)
    ship = _FakeShip(hull=hull, children=[bridge])
    picked = pick_target_subsystem(ship, TGPoint3(0, 50, 0))
    assert picked is hull


def test_returns_none_when_no_hull_and_no_match():
    ship = _FakeShip(hull=None, children=[])
    picked = pick_target_subsystem(ship, TGPoint3(0, 0, 0))
    assert picked is None


def test_picks_closer_of_two_in_range():
    hull = _FakeSubsystem("Hull", TGPoint3(0, 0, 0), 5.0)
    bridge = _FakeSubsystem("Bridge", TGPoint3(0, 5, 0), 2.0)
    aux = _FakeSubsystem("Aux", TGPoint3(0, 6, 0), 2.0)
    ship = _FakeShip(hull=hull, children=[bridge, aux])
    picked = pick_target_subsystem(ship, TGPoint3(0, 5.1, 0))
    assert picked is bridge
