"""Tests for the warp-core breach (engine/appc/warp_core_breach.py)."""
import pytest

from engine.appc import warp_core_breach
from engine.appc.math import TGMatrix3, TGPoint3


class _Core:
    def __init__(self, max_condition=5000.0, pos=None):
        self._max = max_condition
        self._pos = pos or TGPoint3(0.0, 0.0, 0.0)

    def GetMaxCondition(self): return self._max
    def GetPosition(self):     return self._pos


class _Ship:
    def __init__(self, name, loc, radius=1.0, core=None):
        self._name = name
        self._loc = loc
        self._radius = radius
        self._core = core
        self._rot = TGMatrix3()

    def GetName(self):          return self._name
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetRadius(self):        return self._radius
    def GetPowerSubsystem(self): return self._core


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    yield
    warp_core_breach.reset()


def _patch_ships(monkeypatch, ships):
    """Make detonate's iter_ships() yield exactly `ships`."""
    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: list(ships))


def _capture_apply_hit(monkeypatch):
    """Record combat.apply_hit calls as (target, damage, splash_radius)."""
    import engine.appc.combat as combat
    calls = []

    def fake(ship, damage, hit_point, source, **kw):
        calls.append((ship, damage, kw.get("splash_radius")))
    monkeypatch.setattr(combat, "apply_hit", fake)
    return calls


def test_arm_then_advance_detonates_once(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    # Source skipped; near ship hit once.
    targets = [c[0] for c in calls]
    assert near in targets and src not in targets
    # splash_radius forced to the breach radius.
    assert calls[0][2] == warp_core_breach.BREACH_RADIUS_GU


def test_arm_is_single_fire(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.arm(src)        # duplicate arm ignored
    warp_core_breach.advance(0.0)
    warp_core_breach.advance(0.0)    # already breached, no re-detonate
    assert len(calls) == 1


def test_no_core_ship_never_detonates(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Shuttle", TGPoint3(0, 0, 0), core=None)
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)
    assert calls == []


def test_damage_scales_with_core_and_falls_off_with_distance(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    # near at d=0.5, R=0.5: weight = (0.5 + 1.3 - 0.5)/1.3 = 1.0 (clamped)
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    near_dmg = next(d for t, d, _ in calls if t is near)
    # magnitude = 1.0 * 5000 = 5000; weight clamped to 1.0
    assert abs(near_dmg - 5000.0) < 1e-6


def test_ship_outside_radius_untouched(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    # far at d=10, R=0.1: weight = (0.1 + 1.3 - 10)/1.3 < 0 -> 0
    far = _Ship("Far", TGPoint3(10.0, 0, 0), radius=0.1)
    _patch_ships(monkeypatch, [src, far])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)
    assert far not in [c[0] for c in calls]


def test_chain_resolves_same_tick_and_terminates(monkeypatch):
    """An apply_hit that arms a neighbour (mimicking the objects.py hook when a
    neighbour's core hits 0) must detonate that neighbour in the SAME advance,
    and the drain loop must terminate."""
    import engine.appc.combat as combat
    src = _Ship("A", TGPoint3(0, 0, 0), core=_Core(5000.0))
    nbr = _Ship("B", TGPoint3(0.5, 0, 0), radius=0.5, core=_Core(5000.0))
    _patch_ships(monkeypatch, [src, nbr])

    detonated = []
    orig_detonate = warp_core_breach.detonate

    calls = []

    def fake_apply_hit(ship, damage, hit_point, source, **kw):
        calls.append(ship)
        # First time B is hit, simulate its core reaching 0 -> arm.
        if ship is nbr:
            warp_core_breach.arm(nbr)
    monkeypatch.setattr(combat, "apply_hit", fake_apply_hit)

    def tracking_detonate(ship, **kw):
        detonated.append(ship)
        return orig_detonate(ship, **kw)
    monkeypatch.setattr(warp_core_breach, "detonate", tracking_detonate)

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    # Both A and B detonated within the single advance.
    assert src in detonated and nbr in detonated
    # B detonated once (single-fire guard), loop terminated.
    assert detonated.count(nbr) == 1


def test_reset_clears_state(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    _patch_ships(monkeypatch, [src])
    warp_core_breach.arm(src)
    warp_core_breach.reset()
    warp_core_breach.advance(0.0)
    assert calls == []
