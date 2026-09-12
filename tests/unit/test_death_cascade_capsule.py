"""The death cascade's 30% branch also carves a swept capsule on a
breakable ship, so a dying hull can part where no sphere could cut it."""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3


class _Ship:
    def __init__(self, radius):
        self._r = radius; self.damage_calls = []
        self._pts = iter([TGPoint3(1, 0, 0), TGPoint3(-1, 0, 0), TGPoint3(0, 1, 0)])
    def GetRadius(self): return self._r
    def GetRandomPointOnModel(self): return next(self._pts)
    def AddDamage(self, p, r, s): self.damage_calls.append((p, r, s))
    def GetContainingSet(self): return None
    def GetWorldLocation(self): return TGPoint3(0, 0, 0)


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import visible_damage, damage_geometry as dg
    visible_damage._pending.clear() if hasattr(visible_damage, "_pending") else None
    dg.reset()
    yield
    dg.reset()


def _fire_once(ship, roll):
    from engine.appc import death_cascade as dc
    state = {"ship": ship, "rand": lambda n: roll}
    dc._fire(state, sound_ok=False)


def test_breakable_ship_queues_a_capsule_on_the_damage_branch(monkeypatch):
    from engine.appc import visible_damage
    queued = []
    monkeypatch.setattr(visible_damage, "queue_world_capsule",
                        lambda ship, a, b, r: queued.append((a, b, r)))
    ship = _Ship(radius=3.5)
    _fire_once(ship, roll=0)                  # 0 < DAMAGE_CHANCE_IN_10: damage branch
    assert len(ship.damage_calls) == 1        # AddDamage still happens
    assert len(queued) == 1
    (a, b, r), = queued
    from engine.appc.death_cascade import kCascadeCapsuleRadiusGu
    assert r == kCascadeCapsuleRadiusGu
    assert (a.x, b.x) == (1.0, -1.0)          # two DIFFERENT model points


def test_unbreakable_ship_never_queues_a_capsule(monkeypatch):
    from engine.appc import visible_damage
    queued = []
    monkeypatch.setattr(visible_damage, "queue_world_capsule",
                        lambda *a: queued.append(a))
    _fire_once(_Ship(radius=2.38), roll=0)    # Galor
    assert queued == []


def test_capsule_entry_is_emitted_through_host_io_and_then_checks_breakup(monkeypatch):
    from engine.appc import visible_damage, hull_breakup
    emitted, checked = [], []
    monkeypatch.setattr(host_io, "hull_carve_capsule",
                        lambda iid, a, b, r: emitted.append((iid, a, b, r)))
    monkeypatch.setattr(hull_breakup, "after_carve",
                        lambda ship, iid, si=None: checked.append(iid) or [])
    ship = _Ship(radius=3.5)
    visible_damage.queue_world_capsule(ship, TGPoint3(1, 0, 0), TGPoint3(-1, 0, 0), 0.6)
    visible_damage.advance(0.0, ship_instances={ship: 42})
    assert emitted == [(42, (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), 0.6)]
    assert checked == [42]
