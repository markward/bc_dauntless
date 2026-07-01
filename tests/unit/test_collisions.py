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
    hit = _respond_pair(ba, bb)
    assert hit is not None
    # Equal masses -> equal & opposite overlays along +/-x.
    assert a._collision_velocity.x == pytest.approx(-b._collision_velocity.x)
    assert a._collision_velocity.x < 0.0   # A (left) pushed further left
    assert b._collision_velocity.x > 0.0   # B (right) pushed further right


def test_mismatched_mass_light_ship_recoils_more():
    from engine.appc.collisions import _resolve_body, _respond_pair
    light = _ship(0.0, 1000.0, +10.0)
    heavy = _ship(1.5, 5000.0, -10.0)
    _respond_pair(_resolve_body(light), _resolve_body(heavy))
    assert abs(light._collision_velocity.x) > abs(heavy._collision_velocity.x)


def test_ship_vs_immovable_planet_bounces_planet_fixed():
    from engine.appc.collisions import _resolve_body, _respond_pair, _overlay_vec
    ship = _ship(0.0, 1000.0, +10.0)
    planet = Planet_Create(2.0, "")
    planet.SetTranslateXYZ(2.3, 0.0, 0.0)  # dist 2.3 < 0.8*(1+2) = 2.4 scaled boundary
    pre = planet.GetTranslate().x
    _respond_pair(_resolve_body(ship), _resolve_body(planet))
    assert ship._collision_velocity.x < 0.0          # ship recoils
    assert planet.GetTranslate().x == pytest.approx(pre)  # planet unmoved
    assert _overlay_vec(planet) is None              # planet got no impulse


def test_receding_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair, _overlay_vec
    a = _ship(0.0, 1000.0, -10.0)   # moving away from b
    b = _ship(1.5, 1000.0, +10.0)
    hit = _respond_pair(_resolve_body(a), _resolve_body(b))
    assert hit is None
    assert _overlay_vec(a) is None and _overlay_vec(b) is None


def test_non_overlapping_pair_is_ignored():
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(50.0, 1000.0, -10.0)  # far apart
    assert _respond_pair(_resolve_body(a), _resolve_body(b)) is None


def test_radius_scale_allows_closer_approach_before_trigger():
    """Inside the raw bounding-sphere sum (2.0) but outside the scaled
    boundary (0.8 * 2.0 = 1.6) -> no collision yet. Pins the 20% grace
    window that compensates for generous bounding spheres."""
    from engine.appc.collisions import _resolve_body, _respond_pair, _overlay_vec
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.7, 1000.0, -10.0)  # 1.6 < dist 1.7 < 2.0
    hit = _respond_pair(_resolve_body(a), _resolve_body(b))
    assert hit is None
    assert _overlay_vec(a) is None and _overlay_vec(b) is None


def test_respond_pair_invokes_apply_hit_for_both_ships(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg)))
    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    _respond_pair(_resolve_body(a), _resolve_body(b))
    assert len(calls) == 2
    assert {id(a), id(b)} == {id(calls[0][0]), id(calls[1][0])}
    assert all(dmg > 0.0 for _, dmg in calls)


def test_contact_point_refined_to_mesh_when_host_present(monkeypatch):
    """With renderer instance ids, each ship's collision damage lands on ITS
    OWN mesh surface (via host_io.ray_trace_mesh) with the mesh normal, not the
    bounding-sphere point — mirroring the weapons hit path. Task 4: the mesh
    trace routes through host_io, so we patch host_io.ray_trace_mesh."""
    from engine import host_io
    import engine.appc.combat as combat
    captured = []
    monkeypatch.setattr(
        combat, "apply_hit",
        lambda ship, dmg, hit_point, source=None, *, normal=None, **k:
            captured.append((ship, hit_point, normal)))

    def _fake_trace(iid, origin, direction, max_dist):
        # Encode which ship was traced in the surface point's x (= iid),
        # and return a distinctive mesh normal.
        return ((float(iid), 7.0, 7.0), (0.0, 0.0, 1.0), 0.5)

    monkeypatch.setattr(host_io, "ray_trace_mesh", _fake_trace)

    from engine.appc.collisions import _resolve_body, _respond_pair
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    insts = {a: 11, b: 22}
    _respond_pair(_resolve_body(a), _resolve_body(b),
                  ship_instances=insts)

    pts = {id(ship): hp for ship, hp, _n in captured}
    # Each ship's contact point came from its OWN mesh trace (iid-encoded x).
    assert pts[id(a)].x == 11.0 and pts[id(a)].y == 7.0
    assert pts[id(b)].x == 22.0 and pts[id(b)].y == 7.0
    # Mesh surface normal propagated to apply_hit for both ships.
    for _ship_obj, _hp, n in captured:
        assert (n.x, n.y, n.z) == (0.0, 0.0, 1.0)


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
    hits = resolve_collisions([a, b, c])
    assert len(hits) == 1


def test_overlap_persistence_applies_damage_once(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit", lambda *a, **k: calls.append(1))
    from engine.appc.collisions import resolve_collisions
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    resolve_collisions([a, b])   # approaching: 2 hits
    n_after_first = len(calls)
    # After the first resolve, de-penetration separates the pair to exactly
    # touching (dist == sum_r), so the second resolve finds no overlap and
    # applies no further damage — verifying no repeat-damage across frames.
    resolve_collisions([a, b])
    assert n_after_first == 2
    assert len(calls) == 2


def test_iter_collidables_yields_ships_and_planets_only():
    from engine.appc.collisions import iter_collidables
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    ship = _ship(0.0, 1000.0, 0.0)
    planet = Planet_Create(170.0, ""); planet.SetTranslateXYZ(500.0, 0.0, 0.0)
    pSet.AddObjectToSet(ship, "Ship")
    pSet.AddObjectToSet(planet, "Planet")
    found = set(id(o) for o in iter_collidables())
    assert id(ship) in found
    assert id(planet) in found
    assert len(found) == 2  # nothing else (e.g. stubs) leaked through the filter


def test_iter_collidables_skips_zero_radius():
    from engine.appc.collisions import iter_collidables
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    ship = ShipClass()  # radius defaults to 0.0
    pSet.AddObjectToSet(ship, "Ship")
    assert list(iter_collidables()) == []


def test_tick_collisions_resolves_live_set_pair():
    from engine.appc.collisions import tick_collisions
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "test")
    a = _ship(0.0, 1000.0, +10.0)
    b = _ship(1.5, 1000.0, -10.0)
    pSet.AddObjectToSet(a, "A")
    pSet.AddObjectToSet(b, "B")
    hits = tick_collisions(1.0 / 60.0)
    assert len(hits) == 1
    assert a._collision_velocity.x < 0.0 and b._collision_velocity.x > 0.0


def test_tick_collisions_disabled_flag_suppresses_all_effects():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.appc.collisions import tick_collisions, _overlay_vec
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    cheats.set_disable_collisions(True)
    try:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "test")
        a = _ship(0.0, 1000.0, +10.0)
        b = _ship(1.5, 1000.0, -10.0)
        pSet.AddObjectToSet(a, "A")
        pSet.AddObjectToSet(b, "B")
        hits = tick_collisions(1.0 / 60.0, ship_instances=None)
        assert hits == []                  # no pair resolved
        assert _overlay_vec(a) is None      # no impulse injected
        assert _overlay_vec(b) is None
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev


def test_tick_collisions_disabled_still_decays_existing_overlay():
    import _dauntless_host
    import engine.dev_combat_cheats as cheats
    from engine.appc.collisions import tick_collisions, _overlay_vec
    from engine.appc.math import TGPoint3
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    _dauntless_host.developer_mode = True
    cheats.reset()
    cheats.set_disable_collisions(True)
    try:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "test")
        a = _ship(0.0, 1000.0, 0.0)
        a._collision_velocity = TGPoint3(5.0, 0.0, 0.0)
        pSet.AddObjectToSet(a, "A")
        tick_collisions(1.0 / 60.0, ship_instances=None)
        # Overlay path runs before the gate, so the existing overlay decays.
        assert _overlay_vec(a).x < 5.0
    finally:
        cheats.reset()
        _dauntless_host.developer_mode = original_dev
