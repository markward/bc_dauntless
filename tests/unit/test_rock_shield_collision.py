"""Rocks bounce off raised shields (live test 2026-10-01; rock-class spec).

Every collision used to pass bypass_shields=True -- ramming bypasses shields
was confirmed for SHIPS, and rocks inherited it only by subclassing ShipClass.
Now a rock meeting a non-rock ship whose shields are up (combat.shields_block)
meets the ship's shield BUBBLE -- the ellipsoid torpedoes detonate on -- and
the ship's share of the damage cascades through the facing shield. Ship<->ship
is unchanged: both still bypass.

Fixture geometry: hull box half-extents (1, 3, 0.5), so bubble semi-axes are
sqrt(3) x that = (1.732, 5.196, 0.866). The hull sphere is |h| = 3.2, contact
radius 0.8 x 3.2 = 2.56 -- the bubble is FURTHER out than the hull sphere
forward and NEARER in dorsally, so both axes discriminate.
"""
import math

import App
import pytest

from engine.appc import collisions
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ShieldSubsystem
from tests.helpers.one_set import share_one_set
from tests.helpers.shielded_ship import DEFAULT_HALF, make_shielded_ship as _ship

S3 = math.sqrt(3.0)
HALF = DEFAULT_HALF
SEMI = tuple(h * S3 for h in HALF)            # (1.732, 5.196, 0.866)
HULL_R = math.sqrt(sum(h * h for h in HALF))  # 3.2
ROCK_R = 1.0
FRONT, REAR, TOP, BOTTOM = (ShieldSubsystem.FRONT_SHIELDS,
                            ShieldSubsystem.REAR_SHIELDS,
                            ShieldSubsystem.TOP_SHIELDS,
                            ShieldSubsystem.BOTTOM_SHIELDS)


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _rock(pos, vel, name="Rock"):
    from engine.rocks.rock import RockClass_Create
    r = RockClass_Create(ROCK_R, name=name, hull=1.0e9, mass=100.0)
    r.SetRadius(ROCK_R)
    r.SetTranslateXYZ(*pos)
    r.SetVelocity(TGPoint3(*vel))
    return r


def _faces(ship):
    g = ship.GetShields()
    return [g.GetCurrentShields(f) for f in range(ShieldSubsystem.NUM_SHIELDS)]


# -- Contact geometry: the bubble, not the hull sphere ------------------------

@pytest.mark.parametrize("axis, semi", [(1, SEMI[1]), (2, SEMI[2])])
@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_rock_meets_a_shielded_ship_at_the_bubble(axis, semi, gap, collide):
    """Forward (bubble 5.196 > hull 2.56) and dorsal (0.866 < 2.56)."""
    ship = _ship()
    pos = [0.0, 0.0, 0.0]
    pos[axis] = semi + ROCK_R + gap
    vel = [0.0, 0.0, 0.0]
    vel[axis] = -1.0
    rock = _rock(pos, vel)
    share_one_set(ship, rock)
    assert bool(collisions.resolve_collisions([ship, rock])) is collide


@pytest.mark.parametrize("order", ["ship_first", "rock_first"])
def test_bubble_contact_point_normal_and_bounce(order):
    """Contact on the bubble; the rock is pushed back out along the bubble
    normal (+Y here), whichever body is A."""
    ship = _ship()
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.05, 0.0), (0.0, -2.0, 0.0))
    share_one_set(ship, rock)
    objs = [ship, rock] if order == "ship_first" else [rock, ship]
    hits = collisions.resolve_collisions(objs)
    assert len(hits) == 1
    contact = hits[0][2]
    assert contact.x == pytest.approx(0.0, abs=1e-6)
    assert contact.y == pytest.approx(SEMI[1], abs=1e-6)
    assert contact.z == pytest.approx(0.0, abs=1e-6)
    cv = rock.__dict__["_collision_velocity"]
    assert cv.y > 0.0
    assert abs(cv.x) < 1e-9 and abs(cv.z) < 1e-9
    # De-penetrated to rest on the bubble.
    assert rock.GetWorldLocation().y > SEMI[1] + ROCK_R - 0.05


def test_bubble_follows_the_ship_rotation():
    """Ship nose on world +X: the long bubble axis is now along X."""
    ship = _ship()
    ship.AlignToVectors(TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    near = _rock((SEMI[1] + ROCK_R - 1e-3, 0.0, 0.0), (-1.0, 0.0, 0.0))
    share_one_set(ship, near)
    assert collisions.resolve_collisions([ship, near])
    ship2 = _ship()
    ship2.AlignToVectors(TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    # Along world Y is now the ship's (short) lateral axis: 1.732 + 1.
    far = _rock((0.0, SEMI[0] + ROCK_R + 1e-3, 0.0), (0.0, -1.0, 0.0))
    share_one_set(ship2, far)
    assert not collisions.resolve_collisions([ship2, far])


def test_oblique_contact_normal_is_the_ellipsoid_normal():
    """Off-axis: the push is along the bubble's surface normal at the
    closest point, not the centre-to-centre line."""
    ship = _ship()
    # A point outside the bubble in the Y-Z plane, then move it in so the
    # rock overlaps by 0.05 along the exact surface normal.
    t = 0.6
    py, pz = SEMI[1] * math.cos(t), SEMI[2] * math.sin(t)
    gy, gz = py / SEMI[1] ** 2, pz / SEMI[2] ** 2
    gl = math.hypot(gy, gz)
    ny, nz = gy / gl, gz / gl
    d = ROCK_R - 0.05
    rock = _rock((0.0, py + ny * d, pz + nz * d), (0.0, -ny, -nz))
    share_one_set(ship, rock)
    hits = collisions.resolve_collisions([ship, rock])
    assert len(hits) == 1
    c = hits[0][2]
    assert c.y == pytest.approx(py, abs=1e-6)
    assert c.z == pytest.approx(pz, abs=1e-6)
    cv = rock.__dict__["_collision_velocity"]
    n = math.hypot(cv.y, cv.z)
    assert cv.y / n == pytest.approx(ny, abs=1e-6)
    assert cv.z / n == pytest.approx(nz, abs=1e-6)


# -- Damage through the facing -------------------------------------------------

def test_facing_shield_absorbs_and_the_hull_is_untouched():
    ship = _ship()
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    faces = _faces(ship)
    assert faces[FRONT] < 1.0e5
    assert all(f == 1.0e5 for i, f in enumerate(faces) if i != FRONT)
    assert ship.GetHull().GetCondition() == 1.0e6


def test_rock_still_takes_its_own_share():
    ship = _ship()
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    collisions.resolve_collisions([ship, rock])
    assert rock.GetHull().GetCondition() < 1.0e9


def test_dorsal_hit_drains_the_top_face():
    ship = _ship()
    rock = _rock((0.0, 0.0, SEMI[2] + ROCK_R - 0.01), (0.0, 0.0, -5.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    faces = _faces(ship)
    assert faces[TOP] < 1.0e5
    assert all(f == 1.0e5 for i, f in enumerate(faces) if i != TOP)


def test_overflow_reaches_the_hull_once_the_face_is_exhausted():
    ship = _ship(face_max=10.0)
    rock = _rock((0.0, -(SEMI[1] + ROCK_R - 0.01), 0.0), (0.0, 5.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    assert _faces(ship)[REAR] == pytest.approx(0.0)
    mu = 1.0 / (1.0 / 1000.0 + 1.0 / 100.0)
    ke = collisions.COLLISION_DAMAGE_COEFF * 0.5 * mu * 25.0
    assert ship.GetHull().GetCondition() == pytest.approx(1.0e6 - (ke - 10.0))


def test_shield_bounce_posts_the_object_collision_event(monkeypatch):
    seen = []
    monkeypatch.setattr(collisions, "_emit_object_collision",
                        lambda a, b, c, f, off=None: seen.append((a, b, c)))
    ship = _ship()
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    collisions.resolve_collisions([ship, rock])
    assert len(seen) == 1
    assert seen[0][2].y == pytest.approx(SEMI[1], abs=1e-6)


# -- Shields down: today's hull contact, bypass unchanged ---------------------

@pytest.mark.parametrize("gap, collide", [(-1e-3, True), (1e-3, False)])
def test_shields_down_contact_is_the_hull_sphere(gap, collide):
    ship = _ship(shields_up=False)
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    rock = _rock((0.0, reach + gap, 0.0), (0.0, -1.0, 0.0))
    share_one_set(ship, rock)
    assert bool(collisions.resolve_collisions([ship, rock])) is collide


def test_shields_down_damage_goes_to_the_hull():
    ship = _ship(shields_up=False)
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    rock = _rock((0.0, reach - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    assert ship.GetHull().GetCondition() < 1.0e6
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)      # read the stored charge
    assert all(f == 1.0e5 for f in _faces(ship))


def test_shields_dropping_mid_contact_falls_back_to_the_hull():
    """Rock bounced to rest on the dorsal bubble (0.866 + 1); shields drop.
    Dorsally the hull contact sphere (2.56 + 1) is the LARGER one, so next
    frame the rock is inside it and de-penetrates to the hull reach, taking
    hull damage (bypass) as today."""
    ship = _ship()
    rock = _rock((0.0, 0.0, SEMI[2] + ROCK_R - 0.01), (0.0, 0.0, -1.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    ship.SetAlertLevel(ShipClass.GREEN_ALERT)
    rock.SetVelocity(TGPoint3(0.0, 0.0, -1.0))
    rock._collision_velocity = TGPoint3(0.0, 0.0, 0.0)
    hull_before = ship.GetHull().GetCondition()
    assert collisions.resolve_collisions([ship, rock])
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    assert rock.GetWorldLocation().z - ship.GetWorldLocation().z == \
        pytest.approx(reach, abs=1e-6)
    assert ship.GetHull().GetCondition() < hull_before


def test_rock_inside_the_bubble_uses_the_hull_contact():
    """Shields raised with a rock already inside the bubble (it arrived
    while they were down): no shove out to the bubble -- the hull contact
    governs, as a weapon fired from inside the bubble meets the hull."""
    ship = _ship()
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    rock = _rock((0.0, reach - 0.01, 0.0), (0.0, -1.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    assert rock.GetWorldLocation().y == pytest.approx(reach, abs=1e-3)


# -- Ship<->ship unchanged ------------------------------------------------------

@pytest.mark.parametrize("axis", [1, 2])
def test_ship_ship_ramming_still_bypasses_shields(axis):
    """Both shielded; contact at the hull spheres, both hulls damaged, no
    face touched. Dorsally (axis 2) B's centre is OUTSIDE A's bubble, so a
    bubble contact here would be a miss -- that is what pins the rock gate."""
    a = _ship("A")
    b = _ship("B")
    reach = 2.0 * HULL_R * collisions.COLLISION_RADIUS_SCALE
    pos = [0.0, 0.0, 0.0]
    pos[axis] = reach - 0.01
    vel = [0.0, 0.0, 0.0]
    vel[axis] = -5.0
    b.SetTranslateXYZ(*pos)
    b.SetVelocity(TGPoint3(*vel))
    share_one_set(a, b)
    hits = collisions.resolve_collisions([a, b])
    assert len(hits) == 1
    c = (hits[0][2].x, hits[0][2].y, hits[0][2].z)
    assert c[axis] == pytest.approx(HULL_R * collisions.COLLISION_RADIUS_SCALE,
                                    abs=1e-6)
    for s in (a, b):
        assert all(f == 1.0e5 for f in _faces(s))
        assert s.GetHull().GetCondition() < 1.0e6


# -- Grind ----------------------------------------------------------------------

def test_grind_against_the_bubble_drains_the_shield_not_the_hull():
    ship = _ship()
    # Resting overlap on the bubble, sliding sideways (v_rel normal = 0).
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.01, 0.0), (2.0, 0.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock], dt=1.0 / 60.0) == []
    faces = _faces(ship)
    assert faces[FRONT] < 1.0e5
    assert ship.GetHull().GetCondition() == 1.0e6
    assert rock.GetHull().GetCondition() < 1.0e9


# -- Broadphase ----------------------------------------------------------------

def test_broadphase_finds_a_bubble_only_contact(monkeypatch):
    """Hull box (0.2, 3, 0.2): hull sphere 3.013, forward bubble 5.196. The
    ship sits just below a cell boundary so a hull-sphere-sized cell puts the
    rock two cells away; the bubble-sized radius must keep the pair."""
    monkeypatch.setattr(collisions, "_BROADPHASE", True)
    half = (0.2, 3.0, 0.2)
    ship = _ship(half=half)
    ship.SetTranslateXYZ(0.0, -1e-3, 0.0)
    rock = _rock((0.0, -1e-3 + 3.0 * S3 + ROCK_R - 0.01, 0.0), (0.0, -1.0, 0.0))
    share_one_set(ship, rock)
    # Precondition: hull-sphere radii alone would have dropped this pair.
    radii = [collisions.world_radius(ship), collisions.world_radius(rock)]
    pos = [(0.0, -1e-3, 0.0), (0.0, rock.GetWorldLocation().y, 0.0)]
    assert collisions._candidate_pairs(pos, radii, ["S", "S"]) == []
    assert collisions.resolve_collisions([ship, rock])


def test_rock_inside_the_bubble_still_meets_raised_shields():
    """Hull contact (no shove to the bubble), but the shields are UP, so the
    ship's share still cascades through the facing -- as a weapon fired from
    inside the bubble is still absorbed."""
    ship = _ship()
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    rock = _rock((0.0, reach - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    assert collisions.resolve_collisions([ship, rock])
    assert _faces(ship)[FRONT] < 1.0e5
    assert ship.GetHull().GetCondition() == 1.0e6


def test_no_hull_box_hull_contact_but_shields_still_absorb():
    """No cached hull box = no bubble geometry: the hull sphere is the
    contact, but raised shields still take the ship's share."""
    ship = _ship()
    del ship._shield_hull_box
    reach = HULL_R * collisions.COLLISION_RADIUS_SCALE + ROCK_R
    rock = _rock((0.0, reach - 0.01, 0.0), (0.0, -5.0, 0.0))
    share_one_set(ship, rock)
    hits = collisions.resolve_collisions([ship, rock])
    assert hits and hits[0][2].y == pytest.approx(reach - ROCK_R, abs=1e-6)
    assert _faces(ship)[FRONT] < 1.0e5
    assert ship.GetHull().GetCondition() == 1.0e6


# -- The shield FLASH a rock leaves (live 2026-10-01: bounce, but no flash) ---
#
# The flash fired, but at the PER-TICK seed SHIELD_IMPACT_INTENSITY (0.325),
# which exists for a phaser landing every frame (8 summed slots ~ 2.46). A rock
# impact is ONE push, so it drew a quarter of a torpedo's single-impact seed
# (1.3), sized by the 0.15 GU phaser-default radius. Impacts now take the
# single-impact seed and a splash sized to the rock; grind frames are a
# per-frame push and keep the per-tick seed.

def _capture_shield_hits(monkeypatch):
    from engine import host_io
    calls = []

    def spy(iid, point, rgba=(0.0, 0.0, 0.0, 0.0), intensity=1.0, radius=0.0):
        calls.append({"iid": iid, "point": point, "intensity": intensity,
                      "radius": radius})
    monkeypatch.setattr(host_io, "shield_hit", spy)
    return calls


def test_rock_impact_on_shields_flashes_at_the_rock_seed(monkeypatch):
    from engine.appc import hit_feedback
    calls = _capture_shield_hits(monkeypatch)
    ship = _ship()
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.05, 0.0), (0.0, -2.0, 0.0))
    share_one_set(ship, rock)
    collisions.resolve_collisions([ship, rock], ship_instances={ship: 7},
                                  dt=1.0 / 60.0)
    assert len(calls) == 1
    c = calls[0]
    assert c["iid"] == 7
    assert c["point"] == pytest.approx((0.0, SEMI[1], 0.0), abs=1e-6)
    # Fully absorbed (face 1e5 >> damage): the full rock seed, 10x a torpedo's
    # (tuned live 2026-10-01; at the torpedo seed the flash read as invisible).
    assert c["intensity"] == pytest.approx(
        hit_feedback.SHIELD_IMPACT_INTENSITY_ROCK)
    assert hit_feedback.SHIELD_IMPACT_INTENSITY_ROCK == pytest.approx(
        10.0 * hit_feedback.SHIELD_IMPACT_INTENSITY_TORPEDO)
    # Sized to the rock: reach (= radius x 10 in shield_state.h) equals the
    # rock's contact radius -- its full 1.0 GU radius (a rock is its sphere;
    # no 0.8 shrink) -> radius 0.1, reach 1.0 GU (torpedo: 0.13 -> 1.3 GU).
    assert c["radius"] == pytest.approx(
        ROCK_R / hit_feedback.SHIELD_SPLASH_REACH_PER_RADIUS)
    assert c["radius"] == pytest.approx(0.1)


def test_rock_grind_on_shields_keeps_the_per_tick_flash(monkeypatch):
    from engine.appc import hit_feedback
    calls = _capture_shield_hits(monkeypatch)
    ship = _ship()
    # Overlapping the bubble, sliding along it: no closing speed -> grind.
    rock = _rock((0.0, SEMI[1] + ROCK_R - 0.05, 0.0), (1.0, 0.0, 0.0))
    share_one_set(ship, rock)
    for _ in range(3):
        collisions.resolve_collisions([ship, rock], ship_instances={ship: 7},
                                      dt=1.0 / 60.0)
    assert len(calls) == 3
    for c in calls:
        assert c["intensity"] == pytest.approx(
            hit_feedback.SHIELD_IMPACT_INTENSITY)
        assert c["radius"] == pytest.approx(0.15)   # unchanged default


def test_torpedo_and_phaser_shield_flash_unchanged(monkeypatch):
    """Pin the weapon paths: torpedo 1.3 at its DRF, phaser beam 0.325."""
    from engine.appc import combat, hit_feedback
    calls = _capture_shield_hits(monkeypatch)
    ship = _ship()
    src = _ship("Src")

    class _Photon:
        def GetDamageRadiusFactor(self):
            return 0.13
    combat.apply_hit(ship, 500.0, TGPoint3(0.0, 3.0, 0.0), src,
                     weapon_type="torpedo", payload_template=_Photon(),
                     ship_instances={ship: 7},
                     shield_point=TGPoint3(0.0, SEMI[1], 0.0))
    hit_feedback.beam_contact(
        ship=ship, source=src, point=TGPoint3(0.0, 3.0, 0.0), normal=None,
        shield_point=TGPoint3(0.0, SEMI[1], 0.0), tick_damage=1.0,
        ship_instances={ship: 7}, radius=0.15)
    assert [(c["intensity"], c["radius"]) for c in calls] == [
        (pytest.approx(1.3), pytest.approx(0.13)),
        (pytest.approx(0.325), pytest.approx(0.15))]
