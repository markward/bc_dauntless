"""Warp arrival velocity.

Set-to-set warp is a teleport: the ship is removed from one set, added to
another, and placed at a named placement that supplies a NEW orientation.
Chosen behaviour (Mark, 2026-08-09): keep the commanded throttle, re-aim the
velocity along the new facing. Previously nothing set velocity at all, so
arrival velocity was accidental.

This is a CHOSEN default, not recovered BC behaviour — the clean-room reference
could not reach it (best relevance 0.32 against a 0.35 floor).
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


def test_arrival_velocity_follows_the_new_heading(monkeypatch):
    ship = _Placed(speed=4.0, heading=TGPoint3(0.0, 1.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (round(v.x, 6), round(v.y, 6), round(v.z, 6)) == (0.0, 4.0, 0.0)


def test_arrival_velocity_uses_placement_heading_not_pre_warp_heading(monkeypatch):
    """The whole point: the placement re-aims the ship, so a ship that warps
    while pointing +Y must leave along its NEW facing, here +X."""
    ship = _Placed(speed=3.0, heading=TGPoint3(1.0, 0.0, 0.0))
    _run(monkeypatch, ship)
    v = ship.GetVelocity()
    assert (round(v.x, 6), round(v.y, 6), round(v.z, 6)) == (3.0, 0.0, 0.0)


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
