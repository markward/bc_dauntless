"""Objects in different coordinate FRAMES never interact.

Every set has its own set-local origin, and since warp departure stopped
deleting the set you left (Plan 1 Task 4) several sets coexist routinely --
including sets in unrelated star systems whose coordinates overlap
numerically. Collision pairing, splash damage and torpedo hit/homing all
compared raw positions across every set, so after warping Ona1 ->
XiEntrades4 the player's arrival point (0, 5236, 1.5) sat inside Ona 1's
set-local planet sphere and the player struck an invisible planet.

Plan 1 gated all three on `ship_iter.same_set`. Plan 2 (system-frames spec
§1/§6) moves COLLISIONS onto frames: two regions of one star system are one
frame offset by their anchors, so a pair there compares in one set's
coordinates via frames.offset_between; different frames still never meet.
Splash and torpedoes remain on the same_set stopgap here.
Each scenario is paired with its same-set control so a test cannot pass by
excluding everything.
"""
import App
import pytest

from engine.appc.math import TGPoint3
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass
from engine.appc import collisions
from engine.systems import frames
from tests.helpers.mapped_regions import load_region


@pytest.fixture(autouse=True)
def _isolate():
    from engine.appc import projectiles
    App.g_kSetManager._sets.clear()
    projectiles._active.clear()
    yield
    App.g_kSetManager._sets.clear()
    projectiles._active.clear()


def _set(name):
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, name)
    return pSet


def _ship(x, y, z, radius=1.0, mass=1000.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    return s


# ── same_set predicate ───────────────────────────────────────────────────────

def test_same_set_is_identity_of_containing_set():
    from engine.appc.ship_iter import same_set
    a_set, b_set = _set("A"), _set("B")
    a1, a2, b1 = _ship(0, 0, 0), _ship(0, 0, 0), _ship(0, 0, 0)
    a_set.AddObjectToSet(a1, "a1")
    a_set.AddObjectToSet(a2, "a2")
    b_set.AddObjectToSet(b1, "b1")
    assert same_set(a1, a2) is True
    assert same_set(a1, b1) is False


def test_an_object_in_no_set_interacts_with_nothing():
    from engine.appc.ship_iter import same_set
    loose, other_loose = _ship(0, 0, 0), _ship(0, 0, 0)
    assert same_set(loose, other_loose) is False
    a_set = _set("A")
    placed = _ship(0, 0, 0)
    a_set.AddObjectToSet(placed, "placed")
    assert same_set(loose, placed) is False


# ── (a) collisions: the reviewer's Ona1 -> XiEntrades4 scenario ──────────────

def _arriving_player():
    """At the measured XiEntrades4 arrival point, closing on where Ona 1's
    planet sits in ITS set's coordinates (a pair at rest is not a contact)."""
    player = _ship(0.0, 5236.0, 1.5)
    player.SetVelocity(TGPoint3(-1.0, 0.7, 0.0))
    return player


def _ona_planet():
    planet = Planet_Create(1800.0, "")
    planet.SetTranslateXYZ(-972.0, 5917.0, -74.0)
    return planet


def test_player_in_another_set_does_not_strike_a_left_behind_planet():
    """Plain (unmapped) sets are each their own frame, so the left-behind
    planet is in a DIFFERENT frame from the player -- no contact."""
    from engine.appc.collisions import resolve_collisions, tick_collisions
    ona, xi = _set("Ona1"), _set("XiEntrades4")
    planet = _ona_planet()
    ona.AddObjectToSet(planet, "Ona 1")
    player = _arriving_player()
    xi.AddObjectToSet(player, "Player")
    assert frames.offset_between(ona, xi) is None
    assert resolve_collisions([planet, player]) == []
    assert tick_collisions(1.0 / 60.0) == []


def test_the_same_pair_in_one_set_does_collide():
    from engine.appc.collisions import resolve_collisions
    ona = _set("Ona1")
    planet = _ona_planet()
    ona.AddObjectToSet(planet, "Ona 1")
    player = _arriving_player()
    ona.AddObjectToSet(player, "Player")
    assert len(resolve_collisions([planet, player])) == 1


# ── (b) splash damage ────────────────────────────────────────────────────────

def _capture_apply_hit(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, *a, **k: calls.append(ship))
    return calls


def test_splash_does_not_reach_a_ship_at_the_same_coords_in_another_set(monkeypatch):
    from engine.appc import splash_damage
    calls = _capture_apply_hit(monkeypatch)
    a_set, b_set = _set("A"), _set("B")
    boom = _ship(0.0, 0.0, 0.0)
    boom.SetSplashDamage(500.0, 50.0)
    a_set.AddObjectToSet(boom, "Boom")
    neighbour = _ship(5.0, 0.0, 0.0)
    a_set.AddObjectToSet(neighbour, "Neighbour")
    stranger = _ship(5.0, 0.0, 0.0)
    b_set.AddObjectToSet(stranger, "Stranger")
    splash_damage.apply(boom)
    assert neighbour in calls
    assert stranger not in calls


# ── (c) torpedoes: hit and homing ───────────────────────────────────────────

def _torpedo_from(src, vx, vy, vz):
    from engine.appc.projectiles import Torpedo, register
    t = Torpedo()
    p = src.GetWorldLocation()
    t.SetTranslateXYZ(p.x, p.y, p.z)
    t._velocity = TGPoint3(vx, vy, vz)
    t._ttl = 30.0
    t._source_ship = src
    t._damage = 100.0
    register(t)
    return t


def test_torpedo_does_not_hit_a_ship_at_its_coords_in_another_set():
    from engine.appc.projectiles import update_all
    a_set, b_set = _set("A"), _set("B")
    src = _ship(-100.0, 0.0, 0.0)
    a_set.AddObjectToSet(src, "Src")
    stranger = _ship(-99.0, 0.0, 0.0, radius=10.0)
    b_set.AddObjectToSet(stranger, "Stranger")
    t = _torpedo_from(src, 10.0, 0.0, 0.0)
    assert t.GetContainingSet() is a_set
    assert update_all(0.1, [src, stranger]) == []


def test_torpedo_does_hit_a_ship_at_its_coords_in_its_own_set():
    from engine.appc.projectiles import update_all
    a_set = _set("A")
    src = _ship(-100.0, 0.0, 0.0)
    a_set.AddObjectToSet(src, "Src")
    neighbour = _ship(-99.0, 0.0, 0.0, radius=10.0)
    a_set.AddObjectToSet(neighbour, "Neighbour")
    t = _torpedo_from(src, 10.0, 0.0, 0.0)
    hits = update_all(0.1, [src, neighbour])
    assert [(h[0], h[1]) for h in hits] == [(t, neighbour)]


def _homing_torpedo(target_set):
    from engine.appc.projectiles import update_all
    a_set = _set("A")
    b_set = a_set if target_set == "A" else _set("B")
    src = _ship(0.0, 0.0, 0.0)
    a_set.AddObjectToSet(src, "Src")
    target = _ship(0.0, 100.0, 0.0)
    b_set.AddObjectToSet(target, "Target")
    t = _torpedo_from(src, 10.0, 0.0, 0.0)
    t._target_ship = target
    t._guidance_lifetime = 10.0
    t._max_angular_accel = 1.0
    update_all(0.1, [src, target])
    return t


def test_torpedo_does_not_home_on_a_target_in_another_set():
    t = _homing_torpedo("B")
    assert t._velocity.x == 10.0
    assert t._velocity.y == 0.0


def test_torpedo_does_home_on_a_target_in_its_own_set():
    t = _homing_torpedo("A")
    assert t._velocity.y > 0.5


# ── detached hull chunks live in their parent's set ─────────────────────────

def _chunk_scene(other_in_same_set):
    """A chunk severed from a hull in set A, and a ship closing on it that is
    in A or in B. Returns (chunk, ship)."""
    from engine.appc import debris_chunk as dc
    a_set = _set("A")
    b_set = a_set if other_in_same_set else _set("B")
    parent = _ship(0.0, 0.0, 0.0, radius=3.0, mass=120.0)
    a_set.AddObjectToSet(parent, "Parent")
    chunk = dc.spawn(5, parent, 200, (1.0, 0.0, 0.0), 0.5,
                     parent_mass=120.0, parent_occupied_cells=1000)
    chunk._loc = TGPoint3(50.0, 0.0, 0.0)
    rammer = _ship(51.0, 0.0, 0.0)
    rammer.SetVelocity(TGPoint3(-5.0, 0.0, 0.0))
    b_set.AddObjectToSet(rammer, "Rammer")
    return chunk, rammer, a_set


@pytest.fixture
def _no_chunks():
    from engine.appc import debris_chunk as dc
    dc._live.clear()
    yield
    dc._live.clear()


def test_a_chunk_is_in_its_parents_set(_no_chunks):
    chunk, _rammer, a_set = _chunk_scene(other_in_same_set=True)
    assert chunk.GetContainingSet() is a_set


def test_a_chunk_is_struck_by_a_ship_in_its_own_set(_no_chunks):
    from engine.appc.collisions import resolve_collisions
    chunk, rammer, _ = _chunk_scene(other_in_same_set=True)
    assert len(resolve_collisions([chunk, rammer])) == 1


def test_a_chunk_is_not_struck_by_a_ship_in_another_set(_no_chunks):
    from engine.appc.collisions import resolve_collisions
    chunk, rammer, _ = _chunk_scene(other_in_same_set=False)
    assert resolve_collisions([chunk, rammer]) == []


# ── (d) collisions pair by FRAME: two regions of one star system ────────────
# Ona1 and Ona2 are mapped regions of the Ona system, one frame offset by
# their anchors. A pair across them compares in A's set-local coordinates.

def _closing_ship(pSet, name, xyz, vx):
    s = _ship(*xyz, radius=50.0)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    pSet.AddObjectToSet(s, name)
    return s


def test_cross_region_pair_at_the_same_system_position_collides():
    """Two regions of ONE system share a frame: a ship in Ona2 placed at the
    system position of a ship in Ona1 collides with it."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)         # add to Ona2-local -> Ona1-local
    a = _closing_ship(ona1, "A", (0.0, 0.0, 0.0), 0.0)
    b = _closing_ship(ona2, "B", (-off[0] + 60, -off[1], -off[2]), -1.0)  # 60 GU from a in the system
    hits = collisions.resolve_collisions([a, b])
    assert len(hits) == 1


def test_cross_region_pair_with_equal_local_numbers_does_not_collide():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a = _closing_ship(ona1, "A", (0.0, 0.0, 0.0), 0.0)
    b = _closing_ship(ona2, "B", (60.0, 0.0, 0.0), -1.0)    # near only numerically
    assert collisions.resolve_collisions([a, b]) == []


def test_cross_region_depenetration_writes_each_set_local():
    """Review Focus 4: after resolving an overlapping cross-region pair, each
    body's stored position is in its OWN set's coordinates -- b must not be
    written in a's frame."""
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    off = frames.offset_between(ona1, ona2)
    a = _closing_ship(ona1, "A", (0.0, 0.0, 0.0), 0.0)
    b = _closing_ship(ona2, "B", (-off[0] + 60, -off[1], -off[2]), -1.0)
    collisions.resolve_collisions([a, b], dt=1.0 / 60.0)
    bx, by, bz = frames.local_in(ona1, b)
    # b was pushed AWAY from a along +x in the shared frame, and is still
    # within a few hundred GU of a -- not teleported by an anchor's worth.
    assert 60.0 <= bx < 400.0 and abs(by) < 1.0 and abs(bz) < 1.0
    # ...and it really was resolved: an untouched b also sits at 60.
    assert bx > 61.0


# ── (e) _respond_pair is translation-invariant under b_offset ───────────────
# The same physical pair, once with B stored in A's coordinates (offset 0)
# and once with B stored in its own frame (-OFF) and b_offset=OFF, must give
# the same contact, the same A outcome, and B's outcome shifted by -OFF.

_OFF = (1000.0, -250.0, 37.5)


class _Hull:
    def IsDestroyed(self):
        return 0


def _pair_ship(x, y, vx, vy, radius=1.0, pieces=None, spin=None):
    s = _ship(x, y, 0.0, radius=radius, mass=120.0)
    s.SetVelocity(TGPoint3(vx, vy, 0.0))
    s.GetHull = lambda: _Hull()
    s.DamageSystem = lambda sub, dmg, src=None: None
    if pieces is not None:
        from engine.appc.hull_bounds import cache_hull_bound_spheres
        inv = 1.0 / 0.01
        cache_hull_bound_spheres(
            s, [(ox * inv, oy * inv, 0.0, r * inv) for ox, oy, r in pieces])
    if spin is not None:
        s._current_angular_velocity = TGPoint3(*spin)
    return s


def _run_pair(monkeypatch, b_shift, b_offset, *, b_vx, b_vy=0.0, a_vx=0.0,
              a_vy=0.0, pieces=False, spin=None):
    """Resolve one A/B pair with B stored at its A-frame position + b_shift.
    Returns (hit, {ship-key: (hit_point, trace_origin)}, a_pos, b_pos, damage)."""
    from engine import host_io
    import engine.appc.combat as combat
    traces = {}
    monkeypatch.setattr(host_io, "ray_trace_mesh",
                        lambda iid, o, d, m: traces.__setitem__(iid, o) or None)
    points, dmg = {}, {}

    def _hit(ship, damage, hit_point, *a_, **k):
        points[ship._key] = (hit_point.x, hit_point.y, hit_point.z)
        dmg[ship._key] = damage
    monkeypatch.setattr(combat, "apply_hit", _hit)
    sx, sy, sz = b_shift
    a = _pair_ship(0.0, 0.0, a_vx, a_vy,
                   pieces=[(0.2, 0.1, 0.9)] if pieces else None)
    b = _pair_ship(1.5 + sx, 0.3 + sy, b_vx, b_vy,
                   pieces=[(-0.2, 0.0, 0.9)] if pieces else None, spin=spin)
    b.SetTranslateXYZ(1.5 + sx, 0.3 + sy, 0.0 + sz)
    a._key, b._key = "a", "b"
    hit = collisions._respond_pair(collisions._resolve_body(a),
                                   collisions._resolve_body(b),
                                   {a: 1, b: 2}, 1.0 / 60.0,
                                   b_offset=b_offset)
    pa, pb = a.GetTranslate(), b.GetTranslate()
    return (hit, points, traces, (pa.x, pa.y, pa.z), (pb.x, pb.y, pb.z), dmg)


def _neg(v):
    return tuple(-c for c in v)


def _minus(p, off):
    return tuple(pc - oc for pc, oc in zip(p, off))


@pytest.mark.parametrize("case", [
    dict(b_vx=-2.0),                                  # sphere impact
    dict(b_vx=-2.0, pieces=True),                     # piece narrow phase
    dict(b_vx=0.0, b_vy=1.0, spin=(0.0, 0.0, 3.0)),   # rotating grind
    dict(b_vx=0.0, b_vy=1.0, pieces=True),            # piece grind
])
def test_respond_pair_is_translation_invariant_under_b_offset(monkeypatch, case):
    same = _run_pair(monkeypatch, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), **case)
    cross = _run_pair(monkeypatch, _neg(_OFF), _OFF, **case)
    s_hit, s_pts, s_tr, s_pa, s_pb, s_dmg = same
    c_hit, c_pts, c_tr, c_pa, c_pb, c_dmg = cross
    assert s_pts, "fixture produced no contact"
    # Contact (and hence the ET_OBJECT_COLLISION point) is in A's frame.
    assert (s_hit is None) == (c_hit is None)
    if s_hit is not None:
        c = s_hit[2]
        assert (c_hit[2].x, c_hit[2].y, c_hit[2].z) == pytest.approx((c.x, c.y, c.z))
        assert c_hit[3] == pytest.approx(s_hit[3])
    # Damage identical: the rotating arm is measured from B's centre in A's frame.
    assert c_dmg == pytest.approx(s_dmg)
    # A's side is untouched by the offset.
    assert c_pts["a"] == pytest.approx(s_pts["a"])
    assert c_tr[1] == pytest.approx(s_tr[1])
    assert c_pa == pytest.approx(s_pa)
    # B's hit point, trace origin and stored position stay in B's OWN frame.
    assert c_pts["b"] == pytest.approx(_minus(s_pts["b"], _OFF))
    assert c_tr[2] == pytest.approx(_minus(s_tr[2], _OFF))
    assert c_pb == pytest.approx(_minus(s_pb, _OFF))
