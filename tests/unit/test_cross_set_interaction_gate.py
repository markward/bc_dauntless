"""Plan-1 stopgap: objects in DIFFERENT sets never interact.

Every set has its own set-local origin, and since warp departure stopped
deleting the set you left (Plan 1 Task 4) several sets coexist routinely --
including sets in unrelated star systems whose coordinates overlap
numerically. Collision pairing, splash damage and torpedo hit/homing all
compared raw positions across every set, so after warping Ona1 ->
XiEntrades4 the player's arrival point (0, 5236, 1.5) sat inside Ona 1's
set-local planet sphere and the player struck an invisible planet.

The gate is `ship_iter.same_set`; Plan 2's system_position accessor
(docs/superpowers/specs/2026-09-24-system-frames-design.md §1/§6) replaces it.
Each scenario is paired with its same-set control so a test cannot pass by
excluding everything.
"""
import App
import pytest

from engine.appc.math import TGPoint3
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass


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
    from engine.appc.collisions import resolve_collisions, tick_collisions
    ona, xi = _set("Ona1"), _set("XiEntrades4")
    planet = _ona_planet()
    ona.AddObjectToSet(planet, "Ona 1")
    player = _arriving_player()
    xi.AddObjectToSet(player, "Player")
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
