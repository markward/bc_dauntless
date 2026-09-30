"""Collision and hit radii follow GetScale().

GetRadius() is SDK surface and stays UNSCALED (missions read it; the host
sets it from the model at GetScale() == 1), but every object DRAWS at
GetRadius() x GetScale(). E1M2 scales its asteroids 3-8.5x, so a collision
radius of raw GetRadius() let the player fly most of the way into a rock
before contact (Mark, live). The collision broad phase, projectile sphere
hits and the death-splash reach now all use GetRadius() x GetScale().

Rocks are also exempt from COLLISION_RADIUS_SCALE (0.8): that shrink
compensates for a SHIP hull sitting well inside its generous bounding sphere,
while a rock's sphere is its surface.
"""
import App
import pytest

from engine.appc import collisions
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from tests.helpers.one_set import share_one_set


def _rock(radius, scale, x=0.0, vx=0.0, name="R"):
    from engine.rocks.rock import RockClass_Create
    r = RockClass_Create(radius, name=name, hull=1e9, mass=100.0)
    r.SetRadius(radius)            # exact, not quantised
    r.SetScale(scale)
    r.SetTranslateXYZ(x, 0.0, 0.0)
    r.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return r


def _ship(radius, x=0.0, vx=0.0, scale=1.0):
    s = ShipClass()
    s.SetRadius(radius)
    s.SetScale(scale)
    s.SetMass(1000.0)
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return s


def test_a_scaled_rocks_collision_body_is_scale_times_base():
    rock = _rock(1.2, 5.0)
    assert abs(collisions._resolve_body(rock).radius - 6.0) < 1e-9


def test_get_radius_stays_unscaled_and_effective_radius_scales_once():
    """Guard: if GetRadius() ever starts including the scale, effective_radius
    (base x GetScale) and the collision body would both double-scale."""
    from engine.rocks.rock import effective_radius
    rock = _rock(1.2, 5.0)
    assert rock.GetRadius() == pytest.approx(1.2)
    assert effective_radius(rock) == pytest.approx(6.0)
    assert collisions._resolve_body(rock).radius == pytest.approx(
        effective_radius(rock))


@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_two_rocks_collide_exactly_when_they_touch_visually(gap, collide):
    """Rock A draws at 1 x 3 = 3 GU, rock B at 2 x 2 = 4 GU: they touch at 7."""
    a = _rock(1.0, 3.0, x=0.0, vx=1.0, name="A")
    b = _rock(2.0, 2.0, x=7.0 + gap, vx=-1.0, name="B")
    share_one_set(a, b)
    hits = collisions.resolve_collisions([a, b])
    assert bool(hits) is collide


@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_a_ship_keeps_the_boundary_shrink(gap, collide):
    """Two r=10 ships: boundary 0.8 x 20 = 16, unchanged."""
    a = _ship(10.0, x=0.0, vx=1.0)
    b = _ship(10.0, x=16.0 + gap, vx=-1.0)
    share_one_set(a, b)
    assert bool(collisions.resolve_collisions([a, b])) is collide


@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_a_scaled_ship_shrinks_its_scaled_radius(gap, collide):
    """r=10 at scale 2 draws at 20: boundary with an r=10 ship is 0.8 x 30."""
    a = _ship(10.0, x=0.0, vx=1.0, scale=2.0)
    b = _ship(10.0, x=24.0 + gap, vx=-1.0)
    share_one_set(a, b)
    assert bool(collisions.resolve_collisions([a, b])) is collide


@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_rock_ship_boundary_shrinks_only_the_ship(gap, collide):
    """Rock 1 x 5 = 5 (no shrink) + ship 0.8 x 10 = 8: contact at 13."""
    rock = _rock(1.0, 5.0, x=0.0, vx=1.0)
    ship = _ship(10.0, x=13.0 + gap, vx=-1.0)
    share_one_set(rock, ship)
    assert bool(collisions.resolve_collisions([rock, ship])) is collide


def test_broadphase_pairs_a_scaled_rock_it_would_otherwise_drop():
    """The spatial hash's cell comes from the largest radius; an unscaled
    radius made the cell too small for a scaled rock's reach."""
    a = _rock(1.0, 8.0, x=0.0, vx=1.0, name="A")     # draws at 8
    b = _rock(1.0, 8.0, x=15.9, vx=-1.0, name="B")   # touching at 16
    share_one_set(a, b)
    assert collisions.resolve_collisions([a, b])


def test_torpedo_hits_a_scaled_rock_at_its_visible_surface():
    """A torpedo passing 4 GU from a rock of radius 1 drawn at scale 5 is
    inside the rock; the unscaled 1 GU sphere let it fly through."""
    from engine.appc import projectiles
    from engine.appc.projectiles import Torpedo, register, update_all
    projectiles._active.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "ScaleTorp")
    try:
        src = _ship(1.0, x=-100.0)
        pSet.AddObjectToSet(src, "Src")
        rock = _rock(1.0, 5.0, x=0.0)
        rock.SetTranslateXYZ(0.0, 4.0, 0.0)
        pSet.AddObjectToSet(rock, "ScaledRock")
        t = Torpedo()
        t.SetTranslateXYZ(-1.0, 0.0, 0.0)
        t._velocity = TGPoint3(10.0, 0.0, 0.0)
        t._ttl = 30.0
        t._source_ship = src
        t._damage = 1.0
        register(t)
        hits = update_all(0.1, [src, rock])
        assert [(h[0], h[1]) for h in hits] == [(t, rock)]
    finally:
        projectiles._active.clear()
        App.g_kSetManager.DeleteSet("ScaleTorp")


def test_bubble_bound_covers_a_scaled_hull_sphere():
    from engine.appc import combat
    rock = _rock(1.0, 5.0)
    assert combat.bubble_bound_radius(rock) >= 5.0


def test_splash_reach_uses_the_scaled_target_radius(monkeypatch):
    """A death splash of radius 2 centred 6 GU from a ship of radius 1 drawn
    at scale 5 overlaps its visible hull (5 + 2 > 6)."""
    from engine.appc import combat, splash_damage
    hits = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda target, dmg, *a, **k: hits.append((target, dmg)))
    src = _ship(1.0, x=0.0)
    tgt = _ship(1.0, x=6.0, scale=5.0)
    share_one_set(src, tgt)
    pSet = src.GetContainingSet()
    App.g_kSetManager.AddSet(pSet, "ScaleSplash")
    try:
        pSet.AddObjectToSet(src, "Src")
        pSet.AddObjectToSet(tgt, "Tgt")
        src.SetSplashDamage(1000.0, 2.0)
        splash_damage.apply(src)
    finally:
        App.g_kSetManager.DeleteSet("ScaleSplash")
    assert [t for t, _ in hits] == [tgt]


def test_debris_chunk_radius_is_not_multiplied_by_its_render_scale():
    """A DebrisChunk's GetRadius() is already its world size in GU; its
    GetScale() is the RENDER scale of a shared model, not a size factor."""
    from engine.appc import debris_chunk
    c = debris_chunk.DebrisChunk.__new__(debris_chunk.DebrisChunk)
    c.radius, c.scale = 0.3, 57.0
    assert collisions.world_radius(c) == pytest.approx(0.3)


def test_hull_chunk_parent_mask_holds_until_clear_of_the_scaled_parent():
    """debris_chunk releases a chunk's parent mask once it is clear of the
    parent's CONTACT boundary; that boundary now follows the parent's scale,
    so the release must too, or the grind path abrades a scaled parent."""
    from engine.appc import debris_chunk as dc
    from tests.unit.test_debris_chunk import _FakeRenderer, _real_parent
    r = _FakeRenderer()
    parent = _real_parent()
    parent.SetScale(3.0)
    c = dc.spawn(5, parent, 200, (1.0, 0.0, 0.0), 0.5,
                 parent_mass=120.0, parent_occupied_cells=1000)
    p = parent.GetWorldLocation()
    unscaled = (c.GetRadius() + parent.GetRadius()) * collisions.COLLISION_RADIUS_SCALE
    c._loc = TGPoint3(p.x + unscaled + 0.01, p.y, p.z)   # clear only of the raw sphere
    dc.tick(0.0, r)
    assert parent.GetObjID() in collisions._collision_disabled_ids(c)
    clear = c.GetRadius() * collisions.COLLISION_RADIUS_SCALE \
        + collisions.contact_radius(parent)
    c._loc = TGPoint3(p.x + clear + 0.01, p.y, p.z)
    dc.tick(0.0, r)
    assert collisions._collision_disabled_ids(c) == frozenset()
