"""The Python reference for "the first object in a beam's path".

Shooter at the origin, target 100 GU up +Y, aim +Y, contact 95. The mesh trace
is faked (``host_io.ray_trace_mesh``) so each test says where a hull is hit.
"""
import math

import pytest

import App
from engine import host_io
from engine.appc import beam_blockers as bb
from engine.appc import combat
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

EMITTER = TGPoint3(0.0, 0.0, 0.0)
AIM = TGPoint3(0.0, 1.0, 0.0)
CONTACT = 95.0


class World:
    pass


@pytest.fixture
def world(monkeypatch):
    w = World()
    w.set = App.SetClass_Create()
    App.g_kSetManager.AddSet(w.set, "beam_blockers")
    w.ships = []
    w.hits = {}            # iid -> t of the fake mesh hit
    w.instances = {}       # object -> iid
    w.planet_instances = {}
    w._next = [1]

    def fake_trace(iid, o, d, max_dist):
        t = w.hits.get(iid)
        if t is None or t > max_dist:
            return None
        return ((o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t),
                (0.0, -1.0, 0.0), t)

    monkeypatch.setattr(host_io, "ray_trace_mesh", fake_trace)

    def add(name, at, radius=5.0, instance=True, cls=None):
        s = ShipClass_Create(name)
        s.SetTranslateXYZ(*at)
        s.SetRadius(radius)
        w.set.AddObjectToSet(s, name)
        w.ships.append(s)
        if instance:
            w.instances[s] = w._next[0]
            w._next[0] += 1
        return s

    w.add = add
    w.shooter = add("Shooter", (0.0, 0.0, 0.0), instance=False)
    w.target = add("Target", (0.0, 100.0, 0.0), instance=False)

    def hit(obj, t):
        w.hits[w.instances[obj]] = t

    w.hit = hit

    def run(planets=None):
        return bb.first_blocker(w.shooter, w.target, EMITTER, AIM, CONTACT,
                                w.ships, w.planet_instances if planets is None
                                else planets, w.instances)

    w.run = run
    try:
        yield w
    finally:
        App.g_kSetManager.DeleteSet("beam_blockers")


def _shield(ship):
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 1000.0)
    ship._hull = HullSubsystem("Hull")
    ship._hull.SetMaxCondition(1000.0)
    ship.SetShieldSubsystem(ss)
    ship._shield_hull_box = ((0.0, 0.0, 0.0), (4.0, 4.0, 4.0))


def test_ship_in_line_blocks(world):
    b = world.add("B", (0.0, 50.0, 0.0))
    world.hit(b, 48.0)
    r = world.run()
    assert r.kind == "ship" and r.obj is b
    assert r.dist == pytest.approx(48.0)
    assert r.tier == "mesh"


def test_graze_sphere_without_mesh_hit_does_not_block(world):
    world.add("B", (3.0, 50.0, 0.0), radius=5.0)
    assert world.run() is None


def test_no_instance_never_blocks(world):
    b = world.add("B", (0.0, 50.0, 0.0), instance=False)
    assert world.run() is None


def test_shielded_blocker_blocks_at_bubble(world):
    b = world.add("B", (0.0, 50.0, 0.0))
    _shield(b)
    assert combat.shields_block(b)
    expect = combat.shield_bubble_entry(b, EMITTER, AIM, CONTACT)
    assert expect is not None
    r = world.run()
    assert r.tier == "bubble"
    assert (r.bubble.x, r.bubble.y, r.bubble.z) == (expect.x, expect.y, expect.z)
    assert r.dist == pytest.approx(math.sqrt(expect.x ** 2 + expect.y ** 2
                                             + expect.z ** 2))


def test_emitter_inside_candidate_bubble_uses_mesh_only(world):
    b = world.add("B", (0.0, 2.0, 0.0))
    _shield(b)
    assert combat.shield_bubble_entry(b, EMITTER, AIM, CONTACT) is None
    assert world.run() is None


def test_behind_target_never_blocks(world):
    b = world.add("B", (0.0, 150.0, 0.0))
    world.hit(b, 148.0)
    assert world.run() is None


def test_shooter_and_target_excluded(world):
    world.instances[world.shooter] = 90
    world.instances[world.target] = 91
    world.hits[90] = 1.0
    world.hits[91] = 1.0
    assert world.run() is None


def test_dead_and_hidden_excluded(world):
    d = world.add("Dead", (0.0, 40.0, 0.0))
    h = world.add("Hid", (0.0, 50.0, 0.0))
    world.hit(d, 38.0)
    world.hit(h, 48.0)
    d.SetDead()
    h.SetHidden(1)
    assert world.run() is None


def test_other_set_never_blocks(world):
    other = App.SetClass_Create()
    App.g_kSetManager.AddSet(other, "beam_blockers_other")
    try:
        b = world.add("B", (0.0, 50.0, 0.0))
        world.hit(b, 48.0)
        other.AddObjectToSet(b, "B")
        assert world.run() is None
    finally:
        App.g_kSetManager.DeleteSet("beam_blockers_other")


def test_nearest_wins_and_tie_goes_to_earlier(world):
    far = world.add("Far", (0.0, 40.0, 0.0))
    near = world.add("Near", (0.0, 30.0, 0.0))
    world.hit(far, 40.0)
    world.hit(near, 30.0)
    assert world.run().obj is near
    a = world.add("A", (0.0, 60.0, 0.0))
    c = world.add("C", (0.0, 60.0, 0.0))
    world.hits.clear()
    world.hit(a, 60.0)
    world.hit(c, 60.0)
    assert world.run().obj is a


def _planet(world, at, radius=5.0):
    p = Planet(radius)
    p.SetTranslateXYZ(*at)
    world.set.AddObjectToSet(p, "Planet")
    return p


def test_planet_blocks_by_sphere_without_instance(world):
    p = _planet(world, (0.0, 60.0, 0.0))
    r = world.run()
    assert r.kind == "planet" and r.obj is p
    assert r.dist == pytest.approx(55.0)
    assert r.tier == "sphere"


def test_planet_blocks_by_mesh_with_instance(world):
    p = _planet(world, (0.0, 60.0, 0.0))
    world.planet_instances[p] = 77
    world.hits[77] = 54.0
    r = world.run()
    assert r.dist == pytest.approx(54.0)
    assert r.tier == "mesh"


def test_rock_blocks(world):
    from engine.rocks.rock import RockClass
    rk = world.add("Rock", (0.0, 50.0, 0.0))
    rk.__class__ = RockClass
    rk._become_rock()
    world.hit(rk, 47.0)
    r = world.run()
    assert r.kind == "ship" and r.obj is rk


def test_contact_distance():
    pt = TGPoint3(0.0, 3.0, 4.0)
    assert bb.contact_distance(EMITTER, pt, None) == pytest.approx(5.0)
    assert bb.contact_distance(EMITTER, pt, TGPoint3(0.0, 0.0, 2.0)) == pytest.approx(2.0)


def test_step_context_empty_outside_step():
    assert bb.step_ships() == [] and bb.step_planets() == {}
    bb.begin_step([1], {"p": 2})
    assert bb.step_ships() == [1] and bb.step_planets() == {"p": 2}
    bb.end_step()
    assert bb.step_ships() == [] and bb.step_planets() == {}
