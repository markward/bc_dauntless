"""Faithful death-explosion splash damage.

BC's DamageableObject carries m_splashDamage (+0x154) / m_splashDamageRadius
(+0x158), set on every ship by loadspacehelper (MaxCondition*0.1 at radius*2)
and applied by the engine as collateral damage when the object explodes. This
replaces the earlier non-faithful AoE that was hung off the warp-core breach.

See DamageableObject.md sec 5.3, docs/superpowers/specs/.
"""
import pytest

from engine.appc import splash_damage
from engine.appc.objects import DamageableObject
from engine.appc.math import TGPoint3


class _Ship:
    """Minimal splash-carrying object with the accessor surface splash_damage
    needs. Not a full ShipClass — splash_damage only reads geometry + splash."""
    def __init__(self, name, loc, radius=1.0, splash=0.0, splash_radius=0.0):
        self._name = name
        self._loc = loc
        self._radius = radius
        self._splash = splash
        self._splash_radius = splash_radius

    def GetName(self):            return self._name
    def GetWorldLocation(self):   return self._loc
    def GetRadius(self):          return self._radius
    def GetSplashDamage(self):        return self._splash
    def GetSplashDamageRadius(self):  return self._splash_radius


def _capture_apply_hit(monkeypatch):
    import engine.appc.combat as combat
    calls = []

    def fake(ship, damage, hit_point, source, **kw):
        calls.append((ship, damage, kw.get("splash_radius"),
                      kw.get("bypass_shields")))
    monkeypatch.setattr(combat, "apply_hit", fake)
    return calls


def _patch_ships(monkeypatch, ships):
    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: list(ships))


# ── accessors on DamageableObject ────────────────────────────────────────────

def test_splash_defaults_to_zero():
    obj = DamageableObject()
    assert obj.GetSplashDamage() == 0.0
    assert obj.GetSplashDamageRadius() == 0.0


def test_set_splash_stores_amount_and_radius():
    obj = DamageableObject()
    obj.SetSplashDamage(500.0, 12.0)
    assert obj.GetSplashDamage() == 500.0
    assert obj.GetSplashDamageRadius() == 12.0


# ── application ──────────────────────────────────────────────────────────────

def test_apply_hits_nearby_ship_bypassing_shields(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), splash=1000.0, splash_radius=10.0)
    near = _Ship("Near", TGPoint3(1.0, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    splash_damage.apply(src)

    targets = [c[0] for c in calls]
    assert near in targets and src not in targets
    # Explosion damage skips shields, and reports its own splash radius.
    _, _, sr, bypass = calls[0]
    assert sr == 10.0
    assert bypass is True


def test_apply_no_splash_is_noop(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), splash=0.0, splash_radius=0.0)
    near = _Ship("Near", TGPoint3(1.0, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    splash_damage.apply(src)
    assert calls == []


def test_apply_ship_outside_radius_untouched(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), splash=1000.0, splash_radius=10.0)
    far = _Ship("Far", TGPoint3(500.0, 0, 0), radius=0.1)
    _patch_ships(monkeypatch, [src, far])

    splash_damage.apply(src)
    assert far not in [c[0] for c in calls]


def test_apply_no_allegiance_filter(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), splash=1000.0, splash_radius=10.0)
    ally = _Ship("Ally", TGPoint3(1.0, 0, 0), radius=0.5)
    enemy = _Ship("Enemy", TGPoint3(-1.0, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, ally, enemy])

    splash_damage.apply(src)
    hit = [c[0] for c in calls]
    assert ally in hit and enemy in hit
