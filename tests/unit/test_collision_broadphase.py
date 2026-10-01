import math
import random

import App
import pytest

from engine.appc import collisions


class _B:
    def __init__(self, x, y, z, r):
        self.pos = (x, y, z)
        self.radius = r


def _all_pairs_overlapping(bodies):
    out = []
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[k]
            d2 = sum((a.pos[j] - b.pos[j]) ** 2 for j in range(3))
            if d2 <= (a.radius + b.radius) ** 2:
                out.append((i, k))
    return out


def test_candidates_cover_every_overlapping_pair():
    rng = random.Random(7)
    for trial in range(50):
        n = rng.randint(2, 120)
        bodies = [_B(rng.uniform(-60, 60), rng.uniform(-60, 60), rng.uniform(-60, 60),
                     rng.choice([0.2, 0.8, 3.0, 12.0])) for _ in range(n)]
        sets = ["S"] * n
        positions = [b.pos for b in bodies]
        radii = [b.radius for b in bodies]
        cands = collisions._candidate_pairs(positions, radii, sets)
        assert cands == sorted(cands)
        assert set(_all_pairs_overlapping(bodies)) <= set(cands)


def test_distinct_sets_fall_back_to_all_pairs():
    positions = [(0, 0, 0), (1000, 0, 0)]
    cands = collisions._candidate_pairs(positions, [1.0, 1.0], ["A", "B"])
    assert cands == [(0, 1)]


def test_nonfinite_position_does_not_raise_and_pairs_with_every_body():
    positions = [(0.0, 0.0, 0.0), (float("nan"), 0.0, 0.0), (5.0, 5.0, 5.0),
                 (float("inf"), -float("inf"), 0.0)]
    radii = [1.0, 1.0, 1.0, 1.0]
    sets = ["S"] * 4
    cands = collisions._candidate_pairs(positions, radii, sets)   # must not raise
    # body 1 (NaN) and body 3 (+-inf) each pair with every other body in the set
    assert (0, 1) in cands
    assert (1, 2) in cands
    assert (1, 3) in cands
    assert (0, 3) in cands
    assert (2, 3) in cands


def _make_rock(x, y, z, radius=0.8):
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import ShipProperty, HullProperty
    ship = ShipClass_Create("Test")
    ps = ship.GetPropertySet()
    sp = ShipProperty("Mass")
    sp.SetGenus(App.GENUS_ASTEROID)
    sp.SetMass(400.0)
    ps.AddToSet("Scene Root", sp)
    hp = HullProperty("Hull")
    hp.SetMaxCondition(2500.0)
    hp.SetCritical(1)
    hp.SetPrimary(1)
    hp.SetRadius(radius)
    ps.AddToSet("Scene Root", hp)
    ship.SetupProperties()
    # HullProperty.SetRadius feeds the HULL SUBSYSTEM's radius (ships.py's
    # SetupProperties), not ObjectClass.GetRadius() -- the whole-model
    # bounding radius _resolve_body/_candidate_pairs actually read. Set it
    # directly, as every other collisions test does (see test_collisions.py's
    # _ship helper).
    ship.SetRadius(radius)
    ship.SetTranslateXYZ(x, y, z)
    return ship


def _build_cluster(seed, pSet):
    """30 rocks packed into a tight (-3..3 GU) cluster -- close enough that
    plenty of pairs actually overlap at radius 0.8 -- plus one big-radius
    rock (5.0 GU) so the broadphase cell size comes from 2x that radius
    rather than the kBroadphaseMinCellGU floor. Every rock's velocity points
    at the cluster centre, so the cluster is actually closing (v_rel < 0 for
    at least some pairs), not sitting at rest -- resolve_collisions only
    ever appends to its returned hit list on the approaching branch of
    _respond_pair (the receding/resting branch abrades but returns None),
    so a velocity-free cluster exercises no hit at all, however much the
    spheres overlap."""
    from engine.appc.math import TGPoint3
    rng = random.Random(seed)
    rocks = []
    for _ in range(30):
        x, y, z = rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0)
        rock = _make_rock(x, y, z)
        d = math.sqrt(x * x + y * y + z * z)
        if d > 1e-9:
            speed = 3.0
            rock.SetVelocity(TGPoint3(-x / d * speed, -y / d * speed, -z / d * speed))
        rock._containing_set = pSet
        rocks.append(rock)
    # One large body so cell size is driven by 2 x rmax, not the 4.0 floor.
    big = _make_rock(rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0),
                     radius=5.0)
    big._containing_set = pSet
    rocks.append(big)
    return rocks


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_broadphase_resolved_state_matches_all_pairs(monkeypatch, seed):
    from engine.appc.collisions import resolve_collisions
    import engine.appc.collisions as collisions_mod

    monkeypatch.setattr(collisions_mod, "_BROADPHASE", True)
    pSet_on = App.SetClass_Create()
    rocks_on = _build_cluster(seed, pSet_on)
    idx_on = {id(r): i for i, r in enumerate(rocks_on)}
    orig_locs_on = [(l.x, l.y, l.z) for l in (r.GetWorldLocation() for r in rocks_on)]
    hits_on = resolve_collisions(rocks_on, dt=1.0 / 60.0)
    locs_on = [r.GetWorldLocation() for r in rocks_on]
    overlays_on = [r.__dict__.get("_collision_velocity") for r in rocks_on]

    monkeypatch.setattr(collisions_mod, "_BROADPHASE", False)
    pSet_off = App.SetClass_Create()
    rocks_off = _build_cluster(seed, pSet_off)
    idx_off = {id(r): i for i, r in enumerate(rocks_off)}
    hits_off = resolve_collisions(rocks_off, dt=1.0 / 60.0)
    locs_off = [r.GetWorldLocation() for r in rocks_off]
    overlays_off = [r.__dict__.get("_collision_velocity") for r in rocks_off]

    # The whole point of this test: a real, non-empty result, and real
    # motion -- otherwise it would pass even if _candidate_pairs returned [].
    assert len(hits_on) > 0
    moved = any((l.x, l.y, l.z) != orig for l, orig in zip(locs_on, orig_locs_on))
    assert moved

    assert len(hits_on) == len(hits_off)
    pairs_on = [(idx_on[id(a)], idx_on[id(b)]) for a, b, _c, _v in hits_on]
    pairs_off = [(idx_off[id(a)], idx_off[id(b)]) for a, b, _c, _v in hits_off]
    assert pairs_on == pairs_off

    for (a1, b1, c1, v1), (a2, b2, c2, v2) in zip(hits_on, hits_off):
        assert c1.x == pytest.approx(c2.x)
        assert c1.y == pytest.approx(c2.y)
        assert c1.z == pytest.approx(c2.z)
        assert v1 == pytest.approx(v2)

    for loc1, loc2 in zip(locs_on, locs_off):
        assert loc1.x == pytest.approx(loc2.x)
        assert loc1.y == pytest.approx(loc2.y)
        assert loc1.z == pytest.approx(loc2.z)

    for ov1, ov2 in zip(overlays_on, overlays_off):
        if ov1 is None or ov2 is None:
            assert ov1 is None and ov2 is None
        else:
            assert ov1.x == pytest.approx(ov2.x)
            assert ov1.y == pytest.approx(ov2.y)
            assert ov1.z == pytest.approx(ov2.z)
