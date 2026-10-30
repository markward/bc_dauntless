"""ProximityManager.GetNearObjects reads its candidates' positions in one batch.

Every ConditionInRange registers a proximity check with its set's manager, so
in a 64-ship fight each AvoidObstacles query walked ~337 candidates (65 ships
plus ~270 checks) and crossed into the transform store once per candidate:
40% of all AI time. Store-backed objects now share one bulk read; anything
that answers GetWorldLocation itself is still asked. Same objects, same order.
"""
import App
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.planet import ProximityManager
from engine.appc.transform_store import get_store


class _OwnLocation(ObjectClass):
    """An object that answers GetWorldLocation itself (as DebrisChunk,
    subsystems and bridge objects do) -- never read from the store."""

    def __init__(self, xyz):
        super().__init__()
        self._own = TGPoint3(*xyz)

    def GetWorldLocation(self):
        return TGPoint3(self._own.x, self._own.y, self._own.z)


def _ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _scene():
    pSet = App.SetClass_Create()
    near_a = _ship(pSet, "A", (1.0, 0.0, 0.0))
    _ship(pSet, "Far", (500.0, 0.0, 0.0))
    near_b = _ship(pSet, "B", (0.0, 3.0, 0.0))
    pm = ProximityManager(pSet)
    own_near = _OwnLocation((0.0, 0.0, 2.0))
    own_far = _OwnLocation((0.0, 0.0, 900.0))
    pm.AddObject(own_near)
    pm.AddObject(own_far)
    registered = ObjectClass()
    registered.SetTranslateXYZ(4.0, 0.0, 0.0)
    pm.AddObject(registered)
    return pm, [near_a, near_b, own_near, registered]


def test_same_objects_in_set_order_then_registration_order():
    pm, want = _scene()
    got = list(pm.GetNearObjects(TGPoint3(0.0, 0.0, 0.0), 10.0))
    assert got == want


def test_the_radius_boundary_is_inclusive():
    pm, _ = _scene()
    got = list(pm.GetNearObjects(TGPoint3(0.0, 0.0, 0.0), 3.0))
    assert [o.GetWorldLocation().y for o in got][:2] == [0.0, 3.0]
    assert len(got) == 3      # A (1), B (3, on the boundary), own_near (2)


def test_store_backed_objects_are_tested_in_one_store_call(monkeypatch):
    pm, want = _scene()
    cls = type(get_store())
    singles, bulks = [], []
    real_get, real_bulk = cls.get_position, cls.within_radius
    monkeypatch.setattr(cls, "get_position",
                        lambda self, *h: singles.append(h) or real_get(self, *h))
    monkeypatch.setattr(cls, "within_radius",
                        lambda self, hs, *a: bulks.append(list(hs)) or real_bulk(self, hs, *a))
    got = list(pm.GetNearObjects(TGPoint3(0.0, 0.0, 0.0), 10.0))
    assert got == want
    assert singles == []
    assert len(bulks) == 1 and len(bulks[0]) == 4   # 3 ships + registered


def teardown_function(_):
    projectiles._active.clear()
