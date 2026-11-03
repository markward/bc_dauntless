"""Ruling 1: BC's ProximityManager queries never return ProximityChecks.

The per-tick check evaluator (engine/appc/proximity_table.py) does not read
``_candidates``, so skipping checks in the two queries changes no check's
behaviour. See docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md s3.
"""
import App
from engine.appc.ai import ProximityCheck
from engine.appc.math import TGPoint3
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass


def _ship(name, x, y=0.0, z=0.0):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslateXYZ(x, y, z)
    return s


def _check(x=0.0):
    c = ProximityCheck(event_type=999)
    c.SetRadius(50.0)
    c.SetTranslateXYZ(x, 0.0, 0.0)
    return c


def _drain(pm, it):
    out = []
    o = pm.GetNextObject(it)
    while o is not None:
        out.append(o)
        o = pm.GetNextObject(it)
    pm.EndObjectIteration(it)
    return out


def _near(pm):
    return _drain(pm, pm.GetNearObjects(TGPoint3(0, 0, 0), 10.0))


def _line(pm):
    return _drain(pm, pm.GetLineIntersectObjects(
        TGPoint3(-5, 0, 0), TGPoint3(5, 0, 0), 1.0))


def test_near_query_never_returns_a_check_from_the_manager_list():
    s = SetClass_Create()
    a = _ship("A", 0.0)
    s.AddObjectToSet(a, "A")
    pm = s.GetProximityManager()
    pm.AddObject(_check())
    assert _near(pm) == [a]


def test_near_query_never_returns_a_check_that_is_a_set_member():
    s = SetClass_Create()
    a = _ship("A", 0.0)
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(_check(), "C")
    assert _near(s.GetProximityManager()) == [a]


def test_line_query_never_returns_a_check():
    s = SetClass_Create()
    a = _ship("A", 0.0)
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(_check(), "C")
    s.GetProximityManager().AddObject(_check())
    assert _line(s.GetProximityManager()) == [a]


def test_other_objects_keep_their_order_when_checks_are_interleaved():
    s = SetClass_Create()
    a, b = _ship("A", 1.0), _ship("B", 2.0)
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(_check(), "C1")
    s.AddObjectToSet(b, "B")
    pm = s.GetProximityManager()
    pm.AddObject(_check())
    assert _near(pm) == [a, b]
    assert _line(pm) == [a, b]


def test_checks_still_fire_after_exclusion():
    s = SetClass_Create()
    a = _ship("A", 0.0)
    b = _ship("B", 500.0)
    s.AddObjectToSet(a, "A")
    s.AddObjectToSet(b, "B")
    check = ProximityCheck(event_type=999)
    check.SetRadius(100.0)
    check.AddObjectToCheckList(b, ProximityCheck.TT_INSIDE)
    a.AttachObject(check)
    s.GetProximityManager().AddProximityCheck(check, a)

    fired = []
    saved = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(evt.GetEventType())
    try:
        check.Evaluate(a)
        assert 999 not in fired
        b.SetTranslateXYZ(50.0, 0.0, 0.0)
        check.Evaluate(a)
    finally:
        App.g_kEventManager.AddEvent = saved
    assert 999 in fired
