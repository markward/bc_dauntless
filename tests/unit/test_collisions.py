import App
import pytest
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.planet import Planet_Create


def _reset_app_state():
    App.g_kSetManager._sets.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship(x, mass, vx, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return s


def test_resolve_body_ship_is_movable_with_inverse_mass():
    from engine.appc.collisions import _resolve_body
    b = _resolve_body(_ship(5.0, 1000.0, 3.0))
    assert b.is_movable is True
    assert b.inv_mass == pytest.approx(1.0 / 1000.0)
    assert b.center.x == pytest.approx(5.0)
    assert b.radius == pytest.approx(1.0)
    assert b.velocity.x == pytest.approx(3.0)


def test_resolve_body_zero_mass_ship_uses_fallback():
    from engine.appc.collisions import _resolve_body, COLLISION_FALLBACK_MASS
    s = ShipClass(); s.SetRadius(1.0)  # mass defaults to 0.0
    b = _resolve_body(s)
    assert b.inv_mass == pytest.approx(1.0 / COLLISION_FALLBACK_MASS)


def test_resolve_body_planet_is_immovable():
    from engine.appc.collisions import _resolve_body
    p = Planet_Create(170.0, "")
    p.SetTranslateXYZ(0.0, 0.0, 0.0)
    b = _resolve_body(p)
    assert b.is_movable is False
    assert b.inv_mass == 0.0
    assert b.velocity.x == 0.0
    assert b.velocity.y == 0.0
    assert b.velocity.z == 0.0


def test_overlay_vec_returns_none_for_fresh_ship():
    # TGObject.__getattr__ returns a truthy stub for unknown attributes;
    # _overlay_vec must bypass that and return None for a never-collided ship.
    from engine.appc.collisions import _overlay_vec
    assert _overlay_vec(ShipClass()) is None


def test_ensure_overlay_creates_zero_vector_and_reuses_it():
    from engine.appc.collisions import _ensure_overlay
    s = ShipClass()
    cv = _ensure_overlay(s)
    assert cv.x == 0.0
    assert cv.y == 0.0
    assert cv.z == 0.0
    assert _ensure_overlay(s) is cv  # same object on second call, not a fresh one


def test_resolve_body_includes_collision_overlay_in_velocity():
    from engine.appc.collisions import _resolve_body
    s = _ship(0.0, 1000.0, 2.0)
    s._collision_velocity = TGPoint3(5.0, 0.0, 0.0)
    b = _resolve_body(s)
    assert b.velocity.x == pytest.approx(7.0)  # 2.0 thrust + 5.0 overlay


def test_ke_damage_scales_with_velocity_squared():
    from engine.appc.collisions import _ke_damage
    inv_sum = 1.0 / 500.0  # mu = 500
    d1 = _ke_damage(inv_sum, -10.0)
    d2 = _ke_damage(inv_sum, -20.0)
    assert d2 == pytest.approx(4.0 * d1)


def test_symmetric_head_on_equal_opposite_impulse():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)  # overlapping (dist 1.5 < r 1 + r 1)
    ba, bb = _resolve_body(a), _resolve_body(b)
    hit = _respond_pair(ba, bb, 1.0 / 60.0, host=None, ship_instances=None)
    assert hit is not None
    # Equal masses -> equal & opposite overlays along +/-x.
    assert a._collision_velocity.x == pytest.approx(-b._collision_velocity.x)
    assert a._collision_velocity.x < 0.0   # A (left) pushed further left
    assert b._collision_velocity.x > 0.0   # B (right) pushed further right


def test_mismatched_mass_light_ship_recoils_more():
    from engine.appc.collisions import _resolve_body, _respond_pair
    light = _ship(0.0, 1000.0, +10.0)
    heavy = _ship(1.5, 5000.0, -10.0)
    _respond_pair(_resolve_body(light), _resolve_body(heavy),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert abs(light._collision_velocity.x) > abs(heavy._collision_velocity.x)


def test_ship_vs_immovable_planet_bounces_planet_fixed():
    from engine.appc.collisions import _resolve_body, _respond_pair, _overlay_vec
    ship = _ship(0.0, 1000.0, +10.0)
    planet = Planet_Create(2.0, "")
    planet.SetTranslateXYZ(2.5, 0.0, 0.0)  # dist 2.5 < r1 + r2.0 = 3.0
    pre = planet.GetTranslate().x
    _respond_pair(_resolve_body(ship), _resolve_body(planet),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert ship._collision_velocity.x < 0.0          # ship recoils
    assert planet.GetTranslate().x == pytest.approx(pre)  # planet unmoved
    assert _overlay_vec(planet) is None              # planet got no impulse


def test_receding_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair, _overlay_vec
    a = _ship(0.0, 1000.0, -10.0)   # moving away from b
    b = _ship(1.5, 1000.0, +10.0)
    hit = _respond_pair(_resolve_body(a), _resolve_body(b),
                        1.0 / 60.0, host=None, ship_instances=None)
    assert hit is None
    assert _overlay_vec(a) is None and _overlay_vec(b) is None


def test_non_overlapping_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(50.0, 1000.0, -10.0)  # far apart
    assert _respond_pair(_resolve_body(a), _resolve_body(b),
                         1.0 / 60.0, host=None, ship_instances=None) is None


def test_respond_pair_invokes_apply_hit_for_both_ships(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg)))
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    _respond_pair(_resolve_body(a), _resolve_body(b),
                  1.0 / 60.0, host=None, ship_instances=None)
    assert len(calls) == 2
    assert {id(a), id(b)} == {id(calls[0][0]), id(calls[1][0])}
    assert all(dmg > 0.0 for _, dmg in calls)


def test_apply_overlay_moves_and_decays():
    from engine.appc.collisions import _apply_overlay_all, COLLISION_DECAY_TAU
    import math
    s = _ship(0.0, 1000.0, 0.0)
    s._collision_velocity = TGPoint3(6.0, 0.0, 0.0)
    dt = 1.0 / 60.0
    _apply_overlay_all([s], dt)
    assert s.GetTranslate().x == pytest.approx(6.0 * dt)
    assert s._collision_velocity.x == pytest.approx(6.0 * math.exp(-dt / COLLISION_DECAY_TAU))


def test_apply_overlay_skips_objects_without_overlay():
    from engine.appc.collisions import _apply_overlay_all
    s = _ship(3.0, 1000.0, 0.0)
    _apply_overlay_all([s], 1.0 / 60.0)
    assert s.GetTranslate().x == pytest.approx(3.0)        # unmoved
    assert s.__dict__.get("_collision_velocity") is None    # not created


def test_resolve_collisions_returns_one_hit_per_overlapping_pair():
    from engine.appc.collisions import resolve_collisions
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    c = _ship(50.0, 1000.0, 0.0)   # isolated
    hits = resolve_collisions([a, b, c], 1.0 / 60.0)
    assert len(hits) == 1


def test_overlap_persistence_applies_damage_once(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit", lambda *a, **k: calls.append(1))
    from engine.appc.collisions import resolve_collisions
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    resolve_collisions([a, b], 1.0 / 60.0)   # approaching: 2 hits
    n_after_first = len(calls)
    # Still overlapping but now receding (overlays reversed v_rel): no new damage.
    resolve_collisions([a, b], 1.0 / 60.0)
    assert n_after_first == 2
    assert len(calls) == 2
