"""Faithful object lifetime countdown (BC m_lifeTime +0x14c).

DamageableObject carries a lifetime countdown. SetLifeTime(N) marks an object
for timed removal in N seconds; IsDying is derived from it (< g_dyingThreshold).
Mission scripts rely on the engine actually retiring the object — e.g. E7M1
sets a doomed freighter's lifetime to 4.0 and only plays its own explosion
VFX; nothing in the script removes the hull.

See DamageableObject.md sec 5.2, Effects.py:753 (the >1e6 "unset" sentinel).
"""
import pytest

from engine.appc import object_lifetime, objects
from engine.appc.objects import DamageableObject
from engine.appc.math import TGPoint3


class _FakeSet:
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)


class _Obj(DamageableObject):
    def __init__(self, name="Doomed", loc=None, radius=1.0):
        super().__init__()
        self._name = name
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._radius = radius
        self._set = _FakeSet()
    def GetName(self):          return self._name
    def GetWorldLocation(self): return self._loc
    def GetRadius(self):        return self._radius
    def GetContainingSet(self): return self._set


@pytest.fixture(autouse=True)
def _clean():
    object_lifetime.reset()
    yield
    object_lifetime.reset()


# ── accessors + IsDying derivation ──────────────────────────────────────────

def test_lifetime_unset_by_default_and_not_dying():
    obj = DamageableObject()
    # Fresh object reads as "not set" per Effects.py's >1e6 sentinel.
    assert obj.GetLifeTime() > 1_000_000.0
    assert obj.IsDying() == 0


def test_set_lifetime_is_readback():
    obj = _Obj()
    obj.SetLifeTime(4.0)
    assert obj.GetLifeTime() == 4.0


def test_finite_lifetime_reads_as_dying():
    obj = _Obj()
    assert obj.IsDying() == 0
    obj.SetLifeTime(4.0)          # below g_dyingThreshold -> dying
    assert obj.IsDying() == 1


def test_explicit_setdying_still_dying_without_lifetime():
    # The combat death path (ship_death) sets _dying directly; that must keep
    # working independent of the lifetime clock.
    obj = DamageableObject()
    obj.SetDying(True)
    assert obj.IsDying() == 1


# ── countdown + removal ─────────────────────────────────────────────────────

def test_countdown_removes_object_when_expired(monkeypatch):
    from engine.appc import splash_damage
    monkeypatch.setattr(splash_damage, "apply", lambda *a, **k: None)
    obj = _Obj(name="Freighter")
    obj.SetLifeTime(4.0)

    object_lifetime.advance(2.0)
    assert obj.GetContainingSet().removed == []   # still alive
    assert obj.IsDead() == 0

    object_lifetime.advance(2.0)                   # crosses zero
    assert obj.IsDead() == 1
    assert obj.GetContainingSet().removed == ["Freighter"]


def test_expiry_applies_faithful_splash(monkeypatch):
    from engine.appc import splash_damage
    splashed = []
    monkeypatch.setattr(splash_damage, "apply",
                        lambda obj, ship_instances=None: splashed.append(obj))
    obj = _Obj()
    obj.SetLifeTime(1.0)
    object_lifetime.advance(1.0)
    assert splashed == [obj]


def test_unset_lifetime_never_registers_or_expires(monkeypatch):
    from engine.appc import splash_damage
    monkeypatch.setattr(splash_damage, "apply", lambda *a, **k: None)
    obj = _Obj()
    # No SetLifeTime call -> never counts down.
    object_lifetime.advance(10_000.0)
    assert obj.IsDead() == 0
    assert obj.GetContainingSet().removed == []


def test_expiry_is_single_fire(monkeypatch):
    from engine.appc import splash_damage
    splashed = []
    monkeypatch.setattr(splash_damage, "apply",
                        lambda obj, ship_instances=None: splashed.append(obj))
    obj = _Obj(name="Once")
    obj.SetLifeTime(1.0)
    object_lifetime.advance(1.0)
    object_lifetime.advance(1.0)   # already expired + unregistered
    assert splashed == [obj]
    assert obj.GetContainingSet().removed == ["Once"]


def test_reset_clears_registry(monkeypatch):
    from engine.appc import splash_damage
    monkeypatch.setattr(splash_damage, "apply", lambda *a, **k: None)
    obj = _Obj()
    obj.SetLifeTime(1.0)
    object_lifetime.reset()
    object_lifetime.advance(10.0)
    assert obj.IsDead() == 0
