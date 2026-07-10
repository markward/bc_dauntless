import pytest

from engine import host_io
from engine.appc import hit_feedback
from engine.appc.math import TGPoint3


class _Hull:
    def GetConditionPercentage(self): return 1.0
    def IsDestroyed(self): return 0


class _Ship:
    def GetHull(self): return _Hull()


def _dispatch(monkeypatch, *, absorbed_shields, absorbed_hull, weapon_type):
    calls = []
    monkeypatch.setattr(
        "engine.appc.hull_hit_smoke.maybe_emit",
        lambda *a, **k: calls.append((a, k)))
    # Silence the other fan-out branches (audio/shake/carve) for isolation.
    # These are the same host_io no-op patches test_hit_feedback_dispatch.py
    # applies: with the native module loaded, these wrappers reject the
    # plain-int instance ids used by these unit tests (they expect a real
    # _dauntless_host.InstanceId). Only maybe_emit's dispatch is under test
    # here, so the sibling native-touching branches are neutralized.
    monkeypatch.setattr(hit_feedback, "_play_audio", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(1.0, 2.0, 3.0), normal=TGPoint3(0.0, 1.0, 0.0),
        damage=100.0, subsystem=None,
        absorbed_shields=absorbed_shields, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: 3}, weapon_type=weapon_type)
    return calls


def test_hull_hit_calls_smoke(monkeypatch):
    calls = _dispatch(monkeypatch, absorbed_shields=0.0,
                      absorbed_hull=50.0, weapon_type="torpedo")
    assert len(calls) == 1
    (ship, point, normal, wtype, ship_instances), _kw = calls[0]
    assert wtype == "torpedo"
    assert (point.x, point.y, point.z) == (1.0, 2.0, 3.0)


def test_shield_hit_does_not_call_smoke(monkeypatch):
    calls = _dispatch(monkeypatch, absorbed_shields=100.0,
                      absorbed_hull=0.0, weapon_type="torpedo")
    assert calls == []
