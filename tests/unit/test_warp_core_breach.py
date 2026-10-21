"""Tests for the warp-core breach (engine/appc/warp_core_breach.py).

The breach is now a VFX-only dramatic layer: a shockwave ring + Internal hull
damage records growing at the core's world position (their growth is pinned by
tests/unit/test_warp_core_breach_visual.py). It deals NO damage of its own — collateral damage on
death is BC's faithful m_splashDamage, applied by engine.appc.splash_damage from
ship_death.begin (see tests/unit/test_splash_damage.py). This file guards that
the breach spawns its VFX and, crucially, that it never re-grows an AoE damage
loop.
"""
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


def _spy_shockwave(monkeypatch):
    from engine.appc import shockwaves
    spawned = []
    # pSet: the breaching ship's set, which the render feed scopes by.
    monkeypatch.setattr(shockwaves, "spawn",
                        lambda center, max_radius, lifetime, pSet=None:
                        spawned.append((center, max_radius, lifetime)))
    return spawned


def _spy_records(monkeypatch):
    """The core's Internal records, as the instance ids they landed on."""
    from engine import host_io
    from engine.appc import hull_breakup
    records = []
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda iid, *a, **k: records.append(iid))
    monkeypatch.setattr(hull_breakup, "after_wear", lambda *a, **k: [])
    return records


def test_breach_deals_no_damage(monkeypatch):
    """Regression sentinel: the breach must NEVER call combat.apply_hit. Damage
    on death is splash_damage's job now."""
    import engine.appc.combat as combat
    hits = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda *a, **k: hits.append(a))
    _spy_shockwave(monkeypatch)
    _spy_records(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)
    assert hits == []


def test_arm_then_advance_spawns_vfx_once(monkeypatch):
    spawned = _spy_shockwave(monkeypatch)
    records = _spy_records(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    _patch_ships(monkeypatch, [src])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0, ship_instances={src: 5})
    assert len(spawned) == 1
    assert records == [5]


def test_arm_is_single_fire(monkeypatch):
    spawned = _spy_shockwave(monkeypatch)
    _spy_records(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    _patch_ships(monkeypatch, [src])

    warp_core_breach.arm(src)
    warp_core_breach.arm(src)        # duplicate arm ignored
    warp_core_breach.advance(0.0)
    warp_core_breach.advance(0.0)    # already breached, no re-detonate
    assert len(spawned) == 1


def test_no_core_ship_never_detonates(monkeypatch):
    spawned = _spy_shockwave(monkeypatch)
    records = _spy_records(monkeypatch)
    src = _Ship("Shuttle", TGPoint3(0, 0, 0), core=None)
    _patch_ships(monkeypatch, [src])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0, ship_instances={src: 5})
    assert spawned == []
    assert records == []


def test_reset_clears_state(monkeypatch):
    spawned = _spy_shockwave(monkeypatch)
    _spy_records(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    _patch_ships(monkeypatch, [src])
    warp_core_breach.arm(src)
    warp_core_breach.reset()
    warp_core_breach.advance(0.0)
    assert spawned == []


def test_breach_radius_is_forty_gu():
    # Single source of truth for the visual ring radius.
    assert warp_core_breach.BREACH_RADIUS_GU == 40.0


def test_detonate_spawns_one_shockwave_at_core_center(monkeypatch):
    from engine.appc import shockwaves
    spawned = _spy_shockwave(monkeypatch)
    _spy_records(monkeypatch)
    import engine.appc.ship_iter as ship_iter
    src = _Ship("Doomed", TGPoint3(2.0, 0.0, 0.0), core=_Core(5000.0))
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src])

    warp_core_breach.detonate(src)

    assert len(spawned) == 1
    center, max_radius, lifetime = spawned[0]
    # Core at body origin on a ship at (2,0,0), identity rotation -> world (2,0,0).
    assert (round(center.x, 5), round(center.y, 5), round(center.z, 5)) == (2.0, 0.0, 0.0)
    assert max_radius == warp_core_breach.BREACH_RADIUS_GU
    assert lifetime == shockwaves.SHOCKWAVE_LIFETIME


def test_detonate_no_longer_has_spawn_fireball():
    assert not hasattr(warp_core_breach, "_spawn_fireball")


def test_detonate_lays_the_first_core_record(monkeypatch):
    _spy_shockwave(monkeypatch)
    records = _spy_records(monkeypatch)
    import engine.appc.ship_iter as ship_iter
    src = _Ship("Doomed", TGPoint3(0.0, 0.0, 0.0), core=_Core(5000.0))
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src])

    warp_core_breach.detonate(src, ship_instances={src: 3})

    assert records == [3]
