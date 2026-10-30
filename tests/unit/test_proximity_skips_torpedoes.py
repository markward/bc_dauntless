"""The proximity walk must not step through every torpedo in the set.

A torpedo joins its shooter's set (emitter gaps #6/#7), so in a 64-ship fight
a set holds ~1,500 of them. ProximityManager._candidates walked every member
and asked each torpedo its radius -- 0, so it never participated -- on every
AvoidObstacles query: 25% of all AI time in the 64-ship profile.

The set now keeps its non-torpedo members in their own ordered index, and the
walk uses it while no torpedo occupies space. The answer is unchanged: same
objects, same order. A torpedo that IS given a radius still participates,
exactly where the full walk would put it.
"""
import App
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.planet import ProximityManager
from engine.appc.projectiles import Torpedo


def _ship(pSet, name, xyz=(0.0, 0.0, 0.0)):
    s = App.ShipClass_Create()
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _torp(pSet, name, xyz=(0.0, 0.0, 0.0)):
    t = Torpedo()
    pSet.AddObjectToSet(t, name)
    t.SetTranslateXYZ(*xyz)
    return t


def _near(pSet, radius=1000.0):
    return list(ProximityManager(pSet).GetNearObjects(
        TGPoint3(0.0, 0.0, 0.0), radius))


def test_torpedoes_are_not_walked(monkeypatch):
    pSet = App.SetClass_Create()
    ship = _ship(pSet, "Ship")
    for i in range(50):
        _torp(pSet, "Torpedo %d" % i)
    asked = []
    monkeypatch.setattr(Torpedo, "GetRadius",
                        lambda self: asked.append(self) or 0.0)
    assert _near(pSet) == [ship]
    assert asked == []


def test_a_torpedo_with_a_radius_still_participates_in_set_order():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    t = _torp(pSet, "Torpedo 1")
    b = _ship(pSet, "B")
    assert _near(pSet) == [a, b]
    t.SetRadius(0.5)
    assert _near(pSet) == [a, t, b]
    t.SetRadius(0.0)
    assert _near(pSet) == [a, b]


def test_a_sized_torpedo_elsewhere_does_not_slow_this_set(monkeypatch):
    elsewhere = App.SetClass_Create()
    _torp(elsewhere, "Torpedo big").SetRadius(2.0)
    pSet = App.SetClass_Create()
    ship = _ship(pSet, "Ship")
    for i in range(10):
        _torp(pSet, "Torpedo %d" % i)
    asked = []
    monkeypatch.setattr(Torpedo, "GetRadius",
                        lambda self: asked.append(self) or 0.0)
    assert _near(pSet) == [ship]
    assert asked == []


def test_a_name_reused_by_another_kind_keeps_set_order():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    _torp(pSet, "X")
    b = _ship(pSet, "B")
    x = _ship(pSet, "X")         # replaces the torpedo, in ITS slot
    assert list(pSet._objects) == ["A", "X", "B"]
    assert _near(pSet) == [a, x, b]
    _torp(pSet, "A")             # and back the other way
    assert _near(pSet) == [x, b]


def test_removal_and_deletion_drop_members():
    pSet = App.SetClass_Create()
    a = _ship(pSet, "A")
    b = _ship(pSet, "B")
    c = _ship(pSet, "C")
    pSet.RemoveObjectFromSet("A")
    pSet.DeleteObjectFromSet("C")
    assert _near(pSet) == [b]
    assert a.GetContainingSet() is None


def test_line_queries_skip_torpedoes_too(monkeypatch):
    pSet = App.SetClass_Create()
    ship = _ship(pSet, "Ship", (0.0, 50.0, 0.0))
    for i in range(20):
        _torp(pSet, "Torpedo %d" % i, (0.0, 10.0 + i, 0.0))
    asked = []
    monkeypatch.setattr(Torpedo, "GetRadius",
                        lambda self: asked.append(self) or 0.0)
    pm = ProximityManager(pSet)
    hits = list(pm.GetLineIntersectObjects(
        TGPoint3(0.0, 0.0, 0.0), TGPoint3(0.0, 100.0, 0.0), 1.0))
    assert hits == [ship]
    assert asked == []


def teardown_function(_):
    projectiles._active.clear()
