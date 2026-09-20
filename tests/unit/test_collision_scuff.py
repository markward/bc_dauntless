"""Collisions route to the Scuff decal: weapon_type "collision", a contact-chord
decal radius, and the slip direction as the tangent (spec 2026-09-20 §3).

apply_hit is captured at the collision module's own output boundary, the same
seam test_collision_sustained_contact.py uses."""
import math

import pytest

from engine.appc import collisions
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass

GALAXY_MASS = 120.0
FRAME = 1.0 / 60.0


class _Hull:
    def IsDestroyed(self):
        return 0


def _ship(x, mass=GALAXY_MASS, vx=0.0, vy=0.0, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, vy, 0.0))
    s.GetHull = lambda: _Hull()
    s.DamageSystem = lambda sub, dmg, src=None: None
    return s


@pytest.fixture
def hits(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg, k)))
    return calls


def _respond(a, b, dt=FRAME):
    from engine.appc.collisions import _resolve_body, _respond_pair
    return _respond_pair(_resolve_body(a), _resolve_body(b), None, dt)


# ── radius ──────────────────────────────────────────────────────────────────

def test_scuff_radius_is_the_overlap_chord():
    # sqrt(2 * R * pen): R=1, pen=0.5 -> 1.0
    assert collisions.scuff_radius_gu(1.0, 0.5) == pytest.approx(1.0)


def test_scuff_radius_is_clamped_to_the_band():
    assert collisions.scuff_radius_gu(1.0, 1e-6) == collisions.SCUFF_RADIUS_MIN_GU
    assert collisions.scuff_radius_gu(50.0, 50.0) == collisions.SCUFF_RADIUS_MAX_GU
    assert collisions.scuff_radius_gu(1.0, 0.0) == collisions.SCUFF_RADIUS_MIN_GU


# ── impact ──────────────────────────────────────────────────────────────────

def test_impact_hits_are_collision_typed_with_a_decal_radius_and_no_splash_radius(hits):
    a = _ship(0.0, vx=2.0)
    b = _ship(1.5)                       # overlapping: reach = 2 * scale
    assert _respond(a, b) is not None, "fixture did not collide"
    assert len(hits) == 2
    for _ship_, _dmg, kw in hits:
        assert kw["weapon_type"] == "collision"
        assert collisions.SCUFF_RADIUS_MIN_GU <= kw["decal_radius"] <= collisions.SCUFF_RADIUS_MAX_GU
        assert "splash_radius" not in kw, "the scuff size must not widen collision damage"


def test_dead_on_impact_passes_no_tangent(hits):
    a = _ship(0.0, vx=2.0)
    b = _ship(1.5)
    _respond(a, b)
    assert all(kw["hit_tangent"] is None for _s, _d, kw in hits)


def test_oblique_impact_passes_the_tangential_relative_velocity_with_opposite_signs(hits):
    a = _ship(0.0, vx=2.0, vy=1.0)       # closing along +x, sliding along +y
    b = _ship(1.5)
    _respond(a, b)
    ta = next(kw["hit_tangent"] for s, _d, kw in hits if s is a)
    tb = next(kw["hit_tangent"] for s, _d, kw in hits if s is b)
    # b relative to a moves along -y (a slides +y past b) -> a's scratch runs -y.
    assert ta.x == pytest.approx(0.0, abs=1e-9)
    assert ta.y == pytest.approx(-1.0)
    assert tb.y == pytest.approx(+1.0)


# ── grind ───────────────────────────────────────────────────────────────────

def test_grind_hits_are_collision_typed_with_the_slip_as_tangent(hits):
    a = _ship(0.0, vy=1.0)               # resting overlap, sliding sideways
    b = _ship(1.5)
    for _ in range(3):
        _respond(a, b)
    grinds = [(s, kw) for s, _d, kw in hits]
    assert grinds, "fixture did not grind"
    for s, kw in grinds:
        assert kw["weapon_type"] == "collision"
        assert collisions.SCUFF_RADIUS_MIN_GU <= kw["decal_radius"] <= collisions.SCUFF_RADIUS_MAX_GU
        t = kw["hit_tangent"]
        assert t is not None and abs(t.x) < 1e-9
        assert abs(abs(t.y) - 1.0) < 1e-6
    ya = {round(kw["hit_tangent"].y) for s, kw in grinds if s is a}
    yb = {round(kw["hit_tangent"].y) for s, kw in grinds if s is b}
    assert ya == {-1} and yb == {1}, "each hull's scratch runs the way the OTHER hull moved across it"


# ── "collision" must behave exactly like None for audio and smoke (spec §1) ──

def test_hull_smoke_ignores_collision_exactly_like_none(monkeypatch):
    from engine.appc import hull_hit_smoke
    from engine import host_io
    emitted = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a, **k: emitted.append(a))
    # If the weapon gate were to let "collision" through, the next gate is
    # world_to_body; make it succeed so a leak would reach _emit_smoke.
    monkeypatch.setattr(host_io, "world_to_body",
                        lambda *a, **k: ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    ship = _ship(0.0)
    pt, n = TGPoint3(0, 0, 0), TGPoint3(0, 0, 1)
    hull_hit_smoke.maybe_emit(ship, pt, n, None, ship_instances={ship: 1})
    hull_hit_smoke.maybe_emit(ship, pt, n, "collision", ship_instances={ship: 1})
    assert emitted == []
    # Control — the gate is real: a torpedo with a forced roll DOES emit.
    import App
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0,
                        raising=False)
    hull_hit_smoke.maybe_emit(ship, pt, n, "torpedo", ship_instances={ship: 1})
    assert emitted, "control: torpedo smoke should have fired"


def test_hull_audio_picks_the_same_pool_for_collision_and_none(monkeypatch):
    from engine.appc import hit_feedback
    import App
    lookups = []

    class _Snd:
        def Play(self, position=None): return None

    class _Mgr:
        def GetSound(self, name):
            lookups.append(name); return _Snd()

    monkeypatch.setattr(App, "g_kSoundManager", _Mgr(), raising=False)
    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound", lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound", lambda pool: pool[0])
    hit_feedback.reset_audio_throttle()
    hit_feedback._play_audio(hit_feedback.Severity.HULL, TGPoint3(0, 0, 0), None)
    hit_feedback.reset_audio_throttle()
    hit_feedback._play_audio(hit_feedback.Severity.HULL, TGPoint3(0, 0, 0), "collision")
    assert len(lookups) == 2 and lookups[0] == lookups[1]
