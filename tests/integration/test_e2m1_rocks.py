import App
from engine import host_loop
from tests.integration.test_sdk_bridge_load import _fresh_world

E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


def _init_e2m1():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    return mod


def test_asteroid_3_resolves_as_ship_and_is_static_rock():
    """E2M1.py:1079 steers the Karoon at ShipClass_GetObject(..., "Asteroid 3");
    CreateAsteroids SetStatic(TRUE)s every rock."""
    from engine.rocks.rock import is_rock
    mod = _init_e2m1()
    if App.g_kSetManager.GetSet("Beol4").GetObject("Asteroid 3") is None:
        mod.CreateAsteroids()
    a3 = App.ShipClass_GetObject(App.g_kSetManager.GetSet("Beol4"), "Asteroid 3")
    assert a3 is not None and is_rock(a3)
    assert a3.IsImmobile()


def test_karoon_collision_with_asteroid_counts():
    """E2M1.KaroonCollision (E2M1.py:647) ShipClass_Casts the event source."""
    mod = _init_e2m1()
    beol = App.g_kSetManager.GetSet("Beol4")
    if beol.GetObject("Asteroid 3") is None:
        mod.CreateAsteroids()
    rock = App.ShipClass_GetObject(beol, "Asteroid 3")
    called = []
    mod.KaroonHitAsteroid = lambda: called.append(1)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_OBJECT_COLLISION)
    evt.SetSource(rock)
    evt.SetDestination(App.ShipClass_GetObject(beol, "Karoon") or rock)
    # E2M1's own FALSE (E2M1.py:23); BC's App has none, and the shim's
    # App.FALSE is a _NamedStub that would never compare equal.
    mod.g_bKaroonHitAsteroid = mod.FALSE

    class _Owner:
        def CallNextHandler(self, e):
            pass

    mod.KaroonCollision(_Owner(), evt)
    assert called == [1]
