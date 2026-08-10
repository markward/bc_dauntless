"""Warp arrival velocity — EXACTLY ZERO. The ship arrives at rest.

Corrected 2026-08-10 from the clean-room reference. This was briefly implemented
as "keep the commanded throttle, re-aim along the new facing" — a chosen default,
and wrong.

BC derives velocity by one of three rules during drop-out, and at completion the
not-warping entry action sets velocity to the ZERO VECTOR. That was checked
rather than assumed: 243 reads of the vector, one write, all three components
zeroed.

Not a default we get to pick. Do not re-introduce a "preserve throttle" rule
because it feels better to fly.
"""
from engine.appc.math import TGPoint3
from engine.appc.warp import _PlacePlayerAction


class _Placed:
    """Ship double: PlaceObjectByName installs a new heading, as the real
    placement does. Only the surface _do_play touches."""
    def __init__(self, speed, heading):
        self._current_speed = speed
        self._heading = heading
        self._velocity = TGPoint3(0.0, 0.0, 0.0)
        self.placed_as = None
    def GetName(self): return "player"
    def PlaceObjectByName(self, name): self.placed_as = name
    def GetWorldForwardTG(self): return self._heading
    def SetVelocity(self, v): self._velocity = v
    def GetVelocity(self): return self._velocity


class _Set:
    def __init__(self): self.added = []
    def GetObject(self, name): return None
    def RemoveObjectFromSet(self, name): pass
    def AddObjectToSet(self, obj, name): self.added.append(name)


def _run(monkeypatch, ship, dest_name="dest"):
    import App
    dest = _Set()

    class _SetMgr:
        _sets: dict = {}
        def GetSet(self, name): return dest if name == dest_name else None

    monkeypatch.setattr(App, "g_kSetManager", _SetMgr(), raising=False)
    _PlacePlayerAction(ship, dest_name, "placement_a")._do_play()
    return dest


def test_arrival_velocity_is_the_zero_vector(monkeypatch):
    """All three components zeroed, regardless of throttle carried in."""
    ship = _Placed(speed=4.0, heading=TGPoint3(0.0, 1.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_heading_does_not_leak_into_arrival_velocity(monkeypatch):
    """Guards the specific error this replaced: velocity re-aimed along the
    placement's facing. A ship arriving pointing +X must still be at rest."""
    ship = _Placed(speed=3.0, heading=TGPoint3(1.0, 0.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_a_stopped_ship_arrives_stopped(monkeypatch):
    ship = _Placed(speed=0.0, heading=TGPoint3(0.0, 1.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_no_destination_set_leaves_velocity_untouched(monkeypatch):
    """Existing no-op path must stay a no-op — do not stamp velocity on a ship
    that never moved."""
    ship = _Placed(speed=5.0, heading=TGPoint3(0.0, 1.0, 0.0))
    ship.SetVelocity(TGPoint3(9.0, 9.0, 9.0))
    _PlacePlayerAction(ship, "", "placement_a")._do_play()
    v = ship.GetVelocity()
    assert (v.x, v.y, v.z) == (9.0, 9.0, 9.0)
