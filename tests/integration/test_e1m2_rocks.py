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


def test_destroying_every_debris_rock_sets_debris_cleared():
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


def test_moving_asteroid_hitting_haven_counts():
    """The whole beat through the real collision path: a moving asteroid
    driven into Haven reaches E1M2.PlanetCollision -> AsteroidHitPlanet.

    The contact is also lethal to the rock (it dies and breaks up), so it must
    count ONCE, as a planet hit: ET_PLANET_COLLISION is posted before the
    impact damage, and ObjectDestroyed then finds the name already gone."""
    from engine.appc import collisions
    mod = _init_e1m2()
    haven, rock, name = _haven_and_first_rock(mod)
    # Live, host realise sets GetRadius from the mesh; headless nothing does,
    # and a zero-radius object is not collidable at all.
    rock.SetRadius(1.0)
    hit, killed = [], []
    mod.AsteroidHitPlanet = lambda: hit.append(1)
    mod.AsteroidDestroyed = lambda: killed.append(1)
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
    assert killed == []
    assert len(mod.g_dAsteroidInfo) == before - 1
    assert name not in mod.g_dAsteroidInfo
    assert rock.IsDying() or rock.IsDead()       # the contact was lethal


def test_moving_asteroid_striking_the_facility_counts_as_a_station_hit():
    """A group-"e" asteroid driven into the Facility reaches
    E1M2.ObjectCollision -> AsteroidHitStation, through the real collision
    path. The strike is lethal (Asteroid 9e: ~14,500 impact damage against
    3,000 HP), so ET_OBJECT_COLLISION must be posted before the damage, or the
    ET_OBJECT_EXPLODING handler runs first and the beat never fires.

    The asteroid is ALSO counted once by ObjectDestroyed, and must be:
    AsteroidHitStation (E1M2.py:3227) never removes the name from
    g_dAsteroidInfo, and CheckAllDone (E1M2.py:3478) needs
    g_iAsteroidsDestroyed + g_iNumberAsteroidsHit == 5, so an asteroid that
    struck the station and was not counted would leave the mission unwinnable.
    What the ordering fixes is that the station hit is seen FIRST.

    Out of scope: the Facility's own scripted SetVelocity toward the planet
    does not move it (ship scripted velocity, rock-class spec)."""
    from engine.appc import collisions
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    name = "Asteroid 9e"
    assert mod.g_dAsteroidInfo[name][1] == "e"       # ASTER_GROUP
    fac = App.ShipClass_GetObject(pSet, "Facility")
    rock = App.ShipClass_GetObject(pSet, name)
    # Headless nothing realises a mesh radius (see the Haven test).
    fac.SetRadius(3.0)
    rock.SetRadius(0.744)
    beats = []
    mod.AsteroidHitStation = lambda: beats.append("station")
    mod.AsteroidDestroyed = lambda: beats.append("destroyed")
    fp = fac.GetWorldLocation()
    # Clear of the widest boundary any radius rule gives (raw x scale), so
    # the rock is approaching, not born overlapping.
    r = fac.GetRadius() * fac.GetScale() + rock.GetRadius() * rock.GetScale()
    rock.SetTranslateXYZ(fp.x + r + 0.3, fp.y, fp.z)
    rock.SetVelocity(App.TGPoint3(-6.6, 0.0, 0.0))
    loop = GameLoop()
    for _ in range(90):
        loop.tick()
        collisions.tick_collisions(1.0 / 60.0)
    assert rock.IsDying() or rock.IsDead()       # the contact was lethal
    assert beats == ["station", "destroyed"]
    assert name not in mod.g_dAsteroidInfo


def test_asteroid_killed_against_haven_does_not_cascade():
    """A moving asteroid driven into Haven dies on contact and breaks up.
    Its pieces are born inside Haven's boundary; before the fix they kept the
    parent's inward velocity and were not ghosted against Haven, so every
    piece's next contact was lethal too (probe: 87 rocks in 2 s, 230
    ET_PLANET_COLLISIONs). Within 2 s of the strike there must be only the
    parent and its first-generation pieces -- no "-1-1" names."""
    from engine.appc import collisions
    from engine.appc.ship_iter import iter_rocks
    from engine.rocks import breakup
    mod = _init_e1m2()
    haven, rock, name = _haven_and_first_rock(mod)
    rock.SetRadius(1.0)                 # headless: no mesh radius (see above)
    hp = haven.GetWorldLocation()
    # Haven is 1800 GU: start at the narrowest boundary any radius rule
    # gives (0.8 x the raw sum), which is at or inside contact under all of
    # them; the loop below waits for the strike either way.
    r = (haven.GetRadius() + rock.GetRadius()) * collisions.COLLISION_RADIUS_SCALE
    rock.SetTranslateXYZ(hp.x + r + 0.5, hp.y, hp.z)
    rock.SetVelocity(App.TGPoint3(-6.0, 0.0, 0.0))
    strikes = []
    real = collisions._emit_planet_collision

    def spy(a, b):
        strikes.append(1)
        real(a, b)

    collisions._emit_planet_collision = spy
    try:
        loop = GameLoop()
        for _ in range(600):            # until the strike
            loop.tick()
            collisions.tick_collisions(1.0 / 60.0)
            if strikes:
                break
        assert strikes, "the asteroid never reached Haven"
        assert rock.IsDying() or rock.IsDead()
        seen = set()
        for _ in range(120):            # 2 s after it
            loop.tick()
            collisions.tick_collisions(1.0 / 60.0)
            seen.update(x.GetName() for x in iter_rocks()
                        if x.GetName().startswith(name))
    finally:
        collisions._emit_planet_collision = real
    pieces = seen - {name}
    assert 1 <= len(pieces) <= breakup.kPieceCountMax
    assert all(p.count("-") == 1 for p in pieces), sorted(pieces)
    assert len(strikes) == 1


class _NullRenderer:
    def __init__(self):
        self._n = 0

    def __getattr__(self, name):
        def f(*a, **k):
            self._n += 1
            return self._n
        return f


def test_isolated_rock_breakup_does_not_grind_its_siblings(monkeypatch):
    """Scenario A of the 2026-10-01 cascade probe: E1M2's largest moving
    asteroid, alone in space, destroyed outright. Its pieces are born
    overlapping and drift apart over 1-8 s; with a fixed 1 s ghost every
    still-overlapping sibling pair ground every frame afterwards (3,520
    float-noise hit-VFX spawns in 10 s, live: every render frame). Ghosted
    until separated, there must be no sibling grind VFX at all and no death
    beyond the parent.

    kGrindMinDamageRate is pinned to 0 so this guards the ghosting ALONE:
    the grind-rate cutoff would otherwise hide those noise grinds too."""
    from engine.appc import collisions, debris_chunk, hit_vfx
    from engine.appc.ship_iter import iter_ships
    from engine.rocks import chunks as rock_chunks, death
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    rocks = [App.ShipClass_GetObject(pSet, n) for n in mod.g_dAsteroidInfo]
    for s in iter_ships():              # host realise: hull radius when unset
        if s.GetRadius() <= 0.0 and s.GetHull() is not None:
            s.SetRadius(s.GetHull().GetRadius())
    rocks.sort(key=lambda r: -r.GetScale())
    target = rocks[0]
    p0 = target.GetWorldLocation()      # isolate it: everything else far off
    target.SetTranslateXYZ(p0.x, p0.y, p0.z + 3000.0)
    for i, r in enumerate(rocks[1:]):
        q = r.GetWorldLocation()
        r.SetTranslateXYZ(q.x, q.y, q.z - 3000.0 - 50 * i)
    tl = target.GetWorldLocation()
    player = App.Game_GetCurrentGame().GetPlayer()
    if player is not None:
        player.SetTranslateXYZ(tl.x + 500, tl.y, tl.z)
        player.SetVelocity(App.TGPoint3(0, 0, 0))

    grinding = [False]
    grind_vfx = []
    deaths = []
    real_grind, real_spawn, real_begin = (collisions._grind_contact,
                                          hit_vfx.spawn, death.begin)

    def grind(*a, **k):
        grinding[0] = True
        try:
            return real_grind(*a, **k)
        finally:
            grinding[0] = False

    def spawn(*a, **k):
        if grinding[0]:
            grind_vfx.append(1)
        return real_spawn(*a, **k)

    def begin(rock, killer=None):
        if not (death.is_dying_rock(rock) or rock.IsDead()):
            deaths.append(rock.GetName())
        return real_begin(rock, killer)

    monkeypatch.setattr(collisions, "kGrindMinDamageRate", 0.0)
    monkeypatch.setattr(collisions, "_grind_contact", grind)
    monkeypatch.setattr(hit_vfx, "spawn", spawn)
    monkeypatch.setattr(death, "begin", begin)
    target.DamageSystem(target.GetHull(), 1e9)
    renderer = _NullRenderer()
    loop = GameLoop()
    dt = 1.0 / 60.0
    for _ in range(600):                # 10 s
        loop.tick()
        debris_chunk.tick(dt, renderer)
        collisions.tick_collisions(dt)
        rock_chunks.pump(renderer, None)
        death.drain_death_vfx()
    assert deaths == [target.GetName()]
    assert grind_vfx == []
