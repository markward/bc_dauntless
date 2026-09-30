import App
import pytest
from engine import host_loop
from engine.core.loop import GameLoop
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _init_e1m2():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    return mod


def test_moving_asteroids_are_rocks_and_actually_move():
    from engine.rocks.rock import is_rock
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    names = sorted(mod.g_dAsteroidInfo.keys())
    rocks = [App.ShipClass_GetObject(pSet, n) for n in names]
    assert all(r is not None and is_rock(r) for r in rocks)
    start = [r.GetWorldLocation() for r in rocks]
    speeds = [r.GetVelocityTG().Length() for r in rocks]
    GameLoop().advance(120)            # 2 s of game time
    for r, p0, v in zip(rocks, start, speeds):
        p1 = r.GetWorldLocation()
        moved = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 + (p1.z - p0.z) ** 2) ** 0.5
        assert abs(moved - 2.0 * v) < 0.05 * v + 1e-3


def test_clearing_debris_spawns_the_moving_asteroids():
    """E1M2.ObjectDestroyed (E1M2.py:1257) ShipClass_Casts the destroyed
    object; when the last debris rock is destroyed it sets g_bDebrisCleared.
    Destroy every debris rock through the real damage path."""
    mod = _init_e1m2()
    names = list(mod.g_lDebrisNames)
    assert names
    for n in names:
        obj = None
        for pSet in App.g_kSetManager._sets.values():
            obj = pSet.GetObject(n) or obj
        assert obj is not None
        obj.DamageSystem(obj.GetHull(), 1e9)
    GameLoop().advance(60)             # past kRockDeathLife; events dispatch
    assert mod.g_bDebrisCleared


class _Owner:
    def CallNextHandler(self, e):
        pass


def _haven_and_first_rock(mod):
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    name = sorted(mod.g_dAsteroidInfo.keys())[0]
    return (App.Planet_GetObject(pSet, "Haven"),
            App.ShipClass_GetObject(pSet, name), name)


def test_planet_collision_handler_counts_a_rock():
    """E1M2.PlanetCollision (E1M2.py:1308) ShipClass_Casts the destination:
    a rock must pass that cast for the asteroid-hit-Haven beat to count."""
    mod = _init_e1m2()
    haven, rock, name = _haven_and_first_rock(mod)
    assert haven is not None and rock is not None
    hit = []
    mod.AsteroidHitPlanet = lambda: hit.append(1)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_PLANET_COLLISION)
    evt.SetSource(haven)
    evt.SetDestination(rock)
    mod.PlanetCollision(_Owner(), evt)
    assert hit == [1]
    assert name not in mod.g_dAsteroidInfo


@pytest.mark.xfail(strict=True, reason=(
    "No engine emitter for ET_PLANET_COLLISION: BC registers "
    "ShipClass::PlanetCollisionHandler on 0x800052 (decompiled "
    "05_game_mission.c:68141) but engine/appc/collisions.py only posts "
    "ET_OBJECT_COLLISION, so E1M2.PlanetCollision never runs. The rock is "
    "instead destroyed by collision damage and counted by ObjectDestroyed "
    "as a player kill (AsteroidDestroyed), not AsteroidHitPlanet."))
def test_moving_asteroid_hitting_haven_counts():
    """The whole beat through the real collision path: a moving asteroid
    driven into Haven reaches E1M2.PlanetCollision -> AsteroidHitPlanet."""
    from engine.appc import collisions
    mod = _init_e1m2()
    haven, rock, name = _haven_and_first_rock(mod)
    # Live, host realise sets GetRadius from the mesh; headless nothing does,
    # and a zero-radius object is not collidable at all.
    rock.SetRadius(1.0)
    hit = []
    mod.AsteroidHitPlanet = lambda: hit.append(1)
    hp = haven.GetWorldLocation()
    # Just outside the effective boundary (bounding spheres x the scale).
    r = (haven.GetRadius() + rock.GetRadius()) * collisions.COLLISION_RADIUS_SCALE
    rock.SetTranslateXYZ(hp.x + r + 0.5, hp.y, hp.z)
    rock.SetVelocity(App.TGPoint3(-5.0, 0.0, 0.0))
    before = len(mod.g_dAsteroidInfo)
    loop = GameLoop()
    for _ in range(60):
        loop.tick()
        collisions.tick_collisions(1.0 / 60.0)
    assert hit == [1]
    assert len(mod.g_dAsteroidInfo) == before - 1
