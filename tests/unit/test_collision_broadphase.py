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


def _make_rock(x, y, z):
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
    hp.SetRadius(0.8)
    ps.AddToSet("Scene Root", hp)
    ship.SetupProperties()
    ship.SetTranslateXYZ(x, y, z)
    return ship


def _build_cluster(seed, pSet):
    rng = random.Random(seed)
    rocks = []
    for _ in range(30):
        rock = _make_rock(rng.uniform(-10, 10), rng.uniform(-10, 10), rng.uniform(-10, 10))
        rock._containing_set = pSet
        rocks.append(rock)
    return rocks


def test_broadphase_resolved_state_matches_all_pairs(monkeypatch):
    from engine.appc.collisions import resolve_collisions
    import engine.appc.collisions as collisions_mod

    monkeypatch.setattr(collisions_mod, "_BROADPHASE", True)
    pSet_on = App.SetClass_Create()
    rocks_on = _build_cluster(42, pSet_on)
    hits_on = resolve_collisions(rocks_on, dt=1.0 / 60.0)
    locs_on = [r.GetWorldLocation() for r in rocks_on]
    overlays_on = [r.__dict__.get("_collision_velocity") for r in rocks_on]

    monkeypatch.setattr(collisions_mod, "_BROADPHASE", False)
    pSet_off = App.SetClass_Create()
    rocks_off = _build_cluster(42, pSet_off)
    hits_off = resolve_collisions(rocks_off, dt=1.0 / 60.0)
    locs_off = [r.GetWorldLocation() for r in rocks_off]
    overlays_off = [r.__dict__.get("_collision_velocity") for r in rocks_off]

    assert len(hits_on) == len(hits_off)
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
