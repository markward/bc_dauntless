"""ET_PLANET_COLLISION: posted when a body strikes a planet (moons and suns
included -- Sun subclasses Planet here, as in BC where Planet_Cast accepts it).

Evidence is SDK usage only: E1M2.PlanetCollision (E1M2.py:1308) reads
Planet_Cast(GetSource()) and ShipClass_Cast(GetDestination()), so ONE event
per contact, source = the planet, destination = the object. Mirrors the
ET_OBJECT_COLLISION emission (test_collision_event.py): impact path only, so a
resting grind posts nothing.
"""
import App

from engine.appc.math import TGPoint3
from tests.helpers.one_set import share_one_set


def _capture():
    received = []

    def _on(dest, event):
        received.append(event)

    globals()["_on_planet_collision"] = _on
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_PLANET_COLLISION, None, __name__ + "._on_planet_collision")
    return received


def _ship(x, vx):
    from engine.appc.ships import ShipClass_Create
    s = ShipClass_Create("Galaxy")
    s.SetRadius(10.0)
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    return s


def _planet(cls=None):
    from engine.appc.planet import Planet
    p = (cls or Planet)(100.0)
    p.SetTranslateXYZ(0.0, 0.0, 0.0)
    return p


def test_an_object_striking_a_planet_posts_one_planet_collision():
    from engine.appc.collisions import resolve_collisions
    received = _capture()
    planet = _planet()
    ship = _ship(85.0, -5.0)           # inside 0.8 x (100 + 10) = 88, closing
    share_one_set(planet, ship)
    resolve_collisions([planet, ship])
    assert len(received) == 1
    assert received[0].GetSource() is planet
    assert received[0].GetDestination() is ship


def test_argument_order_does_not_change_source_and_destination():
    from engine.appc.collisions import resolve_collisions
    received = _capture()
    planet = _planet()
    ship = _ship(85.0, -5.0)
    share_one_set(planet, ship)
    resolve_collisions([ship, planet])
    assert [(e.GetSource(), e.GetDestination()) for e in received] == [(planet, ship)]


def test_a_sun_counts_as_a_planet():
    from engine.appc.collisions import resolve_collisions
    from engine.appc.planet import Sun
    received = _capture()
    sun = _planet(Sun)
    ship = _ship(85.0, -5.0)
    share_one_set(sun, ship)
    resolve_collisions([sun, ship])
    assert [(e.GetSource(), e.GetDestination()) for e in received] == [(sun, ship)]


def test_once_per_contact_not_every_frame():
    """After the impulse the pair recedes; later frames grind silently."""
    from engine.appc.collisions import resolve_collisions
    received = _capture()
    planet = _planet()
    ship = _ship(85.0, -5.0)
    share_one_set(planet, ship)
    resolve_collisions([planet, ship])
    ship.SetVelocity(TGPoint3(0.0, 0.0, 0.0))   # resting in contact
    for _ in range(5):
        resolve_collisions([planet, ship], dt=1.0 / 60.0)
    assert len(received) == 1


def test_ship_ship_collision_posts_no_planet_collision():
    from engine.appc.collisions import resolve_collisions
    received = _capture()
    a = _ship(0.0, 5.0)
    b = _ship(12.0, -5.0)
    share_one_set(a, b)
    resolve_collisions([a, b])
    assert received == []


def test_a_debris_chunk_striking_a_planet_posts_one_planet_collision():
    """Chunks are withheld from ET_OBJECT_COLLISION (FriendlyFire casts and
    dereferences both parties), but E1M2's only ET_PLANET_COLLISION consumer
    ShipClass_Casts the destination and returns on None, so a chunk is safe."""
    from engine.appc import collisions, debris_chunk as dc
    from tests.unit.test_debris_chunk import _spawn
    received = _capture()
    planet = _planet()
    c = _spawn(dc, centroid=(0.0, 0.0, 0.0))
    c._loc = TGPoint3(80.0, 0.0, 0.0)
    c._vel = TGPoint3(-2.0, 0.0, 0.0)
    hit = collisions._respond_pair(collisions._resolve_body(planet),
                                   collisions._resolve_body(c))
    assert hit is not None
    assert [(e.GetSource(), e.GetDestination()) for e in received] == [(planet, c)]
