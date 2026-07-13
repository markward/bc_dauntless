"""WeaponHitEvent.GetWeaponType() + the PHASER / TORPEDO / TRACTOR_BEAM
constants.

Ground truth is the live-engine constant dump
(tools/probes/results/q13_constants_menu.txt:4059-4062):

    App.WeaponHitEvent.PHASER       = 0
    App.WeaponHitEvent.TORPEDO      = 1
    App.WeaponHitEvent.TRACTOR_BEAM = 2

Three SDK call sites read them: MissionLib.FriendlyFireHandler (excludes
tractor hits from the friendly-fire accumulator), E3M1.AmagonHit (== PHASER)
and E8M2.WeaponHitMatan (== TORPEDO).  The last two reach the constants at
CLASS scope (App.WeaponHitEvent.PHASER), which never goes through
TGObject.__getattr__ — so they must be real class attributes, not stubs.
"""
import pytest

import App
from engine.appc import combat
from engine.appc.events import WeaponHitEvent, ET_WEAPON_HIT
from engine.appc.math import TGPoint3


# ── Constants ───────────────────────────────────────────────────────────────

def test_weapon_type_constants_at_class_scope():
    """E3M1:2177 / E8M2:4862 read these off the CLASS. Values from the q13 dump."""
    assert App.WeaponHitEvent.PHASER == 0
    assert App.WeaponHitEvent.TORPEDO == 1
    assert App.WeaponHitEvent.TRACTOR_BEAM == 2


def test_weapon_type_constants_at_instance_scope():
    """MissionLib:3718 reads pEvent.TRACTOR_BEAM off the INSTANCE."""
    evt = WeaponHitEvent()
    assert evt.PHASER == 0
    assert evt.TORPEDO == 1
    assert evt.TRACTOR_BEAM == 2


def test_weapon_type_round_trip():
    evt = WeaponHitEvent()
    evt.SetWeaponType(App.WeaponHitEvent.TORPEDO)
    assert evt.GetWeaponType() == App.WeaponHitEvent.TORPEDO


def test_distinct_weapon_types_do_not_compare_equal():
    """The bug this fixes: two _Stub values compared EQUAL, so MissionLib's
    `GetWeaponType() == TRACTOR_BEAM` was always true and the friendly-fire
    block never ran on any weapon."""
    evt = WeaponHitEvent()
    evt.SetWeaponType(App.WeaponHitEvent.PHASER)
    assert not (evt.GetWeaponType() == evt.TRACTOR_BEAM)


# ── apply_hit maps its weapon_type string onto the engine int ───────────────

class _Hull:
    def GetCondition(self): return 1000.0
    def IsDestroyed(self): return 0


class _Ship:
    """Unshielded, subsystem-free target: apply_hit routes straight to hull."""
    def __init__(self):
        self._hull = _Hull()
        self._loc = TGPoint3(0.0, 0.0, 0.0)
    def GetHull(self): return self._hull
    def GetShields(self): return None
    def GetWorldLocation(self): return self._loc
    def GetSubsystems(self): return []
    def DamageSystem(self, sub, amount, source=None): pass


@pytest.fixture
def hit_events(monkeypatch):
    """Capture every WeaponHitEvent apply_hit broadcasts."""
    seen = []
    real_add = App.g_kEventManager.AddEvent

    def spy(evt, *a, **k):
        if evt.GetEventType() == ET_WEAPON_HIT:
            seen.append(evt)
        return real_add(evt, *a, **k)

    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return seen


def _hit(weapon_type):
    combat.apply_hit(_Ship(), damage=50.0, hit_point=TGPoint3(0.0, 1.0, 0.0),
                     source=None, weapon_type=weapon_type)


def test_phaser_hit_reports_phaser(hit_events):
    _hit("phaser")
    assert hit_events[0].GetWeaponType() == App.WeaponHitEvent.PHASER


def test_torpedo_hit_reports_torpedo(hit_events):
    """Covers pulse weapons too: BC's disruptor bolts are Torpedo payloads
    (sdk/.../Tactical/Projectiles/CardassianDisruptor.py), so they take the
    torpedo hit path."""
    _hit("torpedo")
    assert hit_events[0].GetWeaponType() == App.WeaponHitEvent.TORPEDO


def test_tractor_hit_reports_tractor_beam(hit_events):
    _hit("tractor")
    assert hit_events[0].GetWeaponType() == App.WeaponHitEvent.TRACTOR_BEAM


def test_kinetic_collision_is_not_any_weapon_type(hit_events):
    """Collisions call apply_hit with weapon_type=None. BC's engine has no
    enum value for a ram, so we report a sentinel that matches NONE of the
    three — otherwise a ram would satisfy E3M1's `== PHASER` mission gate."""
    _hit(None)
    wt = hit_events[0].GetWeaponType()
    assert wt == WeaponHitEvent.NON_WEAPON
    assert wt != App.WeaponHitEvent.PHASER
    assert wt != App.WeaponHitEvent.TORPEDO
    assert wt != App.WeaponHitEvent.TRACTOR_BEAM


def test_unknown_weapon_type_string_is_not_any_weapon_type(hit_events):
    """An unmapped string must not silently masquerade as a phaser (0)."""
    _hit("photonic_death_ray")
    assert hit_events[0].GetWeaponType() == WeaponHitEvent.NON_WEAPON
