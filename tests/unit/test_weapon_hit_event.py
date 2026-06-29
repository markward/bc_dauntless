"""WeaponHitEvent — TGEvent subclass carrying source/target/damage/
hit_point/subsystem. ET_WEAPON_HIT broadcast via g_kEventManager.
"""
from engine.appc.events import (
    TGEventManager, TGEventHandlerObject, WeaponHitEvent, ET_WEAPON_HIT,
)
from engine.appc.math import TGPoint3


class _Recorder(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self.received = []

    def ProcessEvent(self, evt):
        self.received.append(evt)


def test_weapon_hit_event_defaults():
    e = WeaponHitEvent()
    assert e.GetEventType() == ET_WEAPON_HIT
    assert e.GetSource() is None
    assert e.GetTarget() is None
    assert e.GetDamage() == 0.0
    assert e.GetHitPoint() is None
    assert e.GetSubsystem() is None


def test_weapon_hit_event_roundtrip():
    src = object()
    tgt = object()
    sub = object()
    pt = TGPoint3(1, 2, 3)
    e = WeaponHitEvent()
    e.SetSource(src)
    e.SetTarget(tgt)
    e.SetDamage(500.0)
    e.SetHitPoint(pt)
    e.SetSubsystem(sub)
    assert e.GetSource() is src
    assert e.GetTarget() is tgt
    assert e.GetDamage() == 500.0
    assert e.GetHitPoint() is pt
    assert e.GetSubsystem() is sub


def test_weapon_hit_event_dispatched_to_destination():
    em = TGEventManager()
    dest = _Recorder()
    e = WeaponHitEvent()
    e.SetDestination(dest)
    e.SetDamage(42.0)
    em.AddEvent(e)
    assert len(dest.received) == 1
    assert dest.received[0].GetDamage() == 42.0


def test_weapon_hit_event_broadcast_handler_fires():
    em = TGEventManager()
    received = []
    def handler(_obj, evt):
        received.append(evt.GetDamage())
    import sys, types
    mod = types.ModuleType("_test_weapon_hit_handler")
    mod.handler = handler
    sys.modules["_test_weapon_hit_handler"] = mod
    em.AddBroadcastPythonFuncHandler(ET_WEAPON_HIT, None,
                                      "_test_weapon_hit_handler.handler")
    e = WeaponHitEvent()
    e.SetDamage(99.0)
    em.AddEvent(e)
    assert received == [99.0]
    del sys.modules["_test_weapon_hit_handler"]


def test_weapon_hit_event_radius_round_trip():
    from engine.appc.events import WeaponHitEvent
    evt = WeaponHitEvent()
    assert evt.GetRadius() == 0.0
    evt.SetRadius(0.15)
    assert evt.GetRadius() == 0.15


def test_weapon_hit_event_normal_round_trip():
    from engine.appc.events import WeaponHitEvent
    from engine.appc.math import TGPoint3
    evt = WeaponHitEvent()
    assert evt.GetNormal() is None
    n = TGPoint3(0.0, 0.0, 1.0)
    evt.SetNormal(n)
    out = evt.GetNormal()
    assert out is n  # identity, not a copy


def test_weapon_hit_event_is_hull_hit_defaults_to_zero():
    """ConditionAttacked/AttackedBy call IsHullHit(); a freshly-built event
    (shields-absorbed by default) must report 0."""
    evt = WeaponHitEvent()
    assert evt.IsHullHit() == 0


def test_weapon_hit_event_set_hull_hit_true():
    evt = WeaponHitEvent()
    evt.SetHullHit(True)
    assert evt.IsHullHit() == 1


def test_weapon_hit_event_set_hull_hit_false():
    evt = WeaponHitEvent()
    evt.SetHullHit(True)
    evt.SetHullHit(False)
    assert evt.IsHullHit() == 0
