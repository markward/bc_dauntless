"""Task 4 of the host_io façade refactor: the combat/damage subsystem's native
hit/damage touches route through the engine.host_io wrappers (the single
manifest-validated guard point), not a raw _dauntless_host handle threaded via
host=.

These tests patch the specific host_io.NAME wrapper and assert the damage path
drives it — the same idiom Tasks 2 & 3 established for the input/window pollers
and the 6 VFX setters.
"""
import pytest

from engine import host_io
from engine.appc import combat
from engine.appc.math import TGPoint3


class _Shield:
    """Front face charged; ApplyDamage absorbs up to the charge, returns
    overflow. shields_online in apply_hit needs IsOn/IsDisabled/IsDestroyed."""
    def __init__(self, front_charge):
        self._c = [0.0] * 6
        self._c[0] = float(front_charge)
    def IsOn(self): return 1
    def IsDisabled(self): return 0
    def IsDestroyed(self): return 0
    def GetCurrentShields(self, face): return self._c[face]
    def ApplyDamage(self, face, dmg):
        absorb = min(self._c[face], dmg)
        self._c[face] -= absorb
        return dmg - absorb


class _Hull:
    def GetCondition(self): return 1000.0
    def IsDestroyed(self): return 0


class _Ship:
    def __init__(self, shields):
        self._shields = shields
        self._hull = _Hull()
        self._loc = TGPoint3(0.0, 0.0, 0.0)
    def GetHull(self): return self._hull
    def GetShields(self): return self._shields
    def GetWorldLocation(self): return self._loc
    def GetSubsystems(self): return []
    def DamageSystem(self, sub, amount): pass


def test_apply_hit_shield_hit_routes_through_host_io(monkeypatch):
    """A shields-absorbed hit fires the shield flash via host_io.shield_hit
    (positional args), with the ship's renderer instance id and impact point."""
    calls = []
    monkeypatch.setattr(host_io, "shield_hit",
                        lambda instance_id, point, rgba=(0, 0, 0, 0), intensity=1.0:
                        calls.append((instance_id, point, rgba, intensity)))
    # Neutralize the sibling wrappers so nothing else reaches the real native.
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)

    ship = _Ship(_Shield(front_charge=1000.0))
    point = TGPoint3(0.0, 1.0, 0.0)  # FRONT face — body +Y.
    combat.apply_hit(ship, damage=30.0, hit_point=point, source=None,
                     normal=None, ship_instances={ship: 77},
                     weapon_type="torpedo")

    assert len(calls) == 1, "apply_hit did not route the shield flash through host_io"
    instance_id, pt, rgba, intensity = calls[0]
    assert instance_id == 77
    assert pt == (0.0, 1.0, 0.0)
    # (0,0,0,0) is the sentinel that tells the shield pass to use the ship's
    # registered ShieldGlowColor.
    assert rgba == (0.0, 0.0, 0.0, 0.0)
    assert intensity == 1.0


def test_apply_hit_shield_flash_skipped_without_instance(monkeypatch):
    """No renderer instance mapping -> shield flash skipped, host_io.shield_hit
    is never called, and apply_hit does not raise."""
    calls = []
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)

    ship = _Ship(_Shield(front_charge=1000.0))
    combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0.0, 1.0, 0.0),
                     source=None, normal=None, ship_instances=None,
                     weapon_type="torpedo")
    assert calls == []
