"""E1M2 asteroid-warning regression: CreateMovingAsteroids must not crash.

After the Soams comm cutscene warns of incoming asteroids, the comm sequence
fires E1M2.CreateMovingAsteroids. Two engine/compat gaps used to break it:

* Fatal: `lAsteroids = g_dAsteroidInfo.keys(); lAsteroids.sort()` (E1M2.py:3016)
  crashed under Py3 ('dict_keys' has no .sort()). Fixed by generalizing the SDK
  loader's dict-view AST transform (conftest _FixDictKeysIter /
  tools.mission_harness _FixPy2DictView) to wrap every no-arg
  .keys()/.values()/.items() call in list(), not just for-loop iterables.

* Swallowed: the AsteroidExploding death script raised
  `TypeError: attribute name must be string, not '_Stub'` because
  ShipClass.GetShipProperty() was unimplemented — it fell through to a _Stub,
  so Effects.GetDeathExplosionSound()'s getattr(mod, <_Stub>) blew up. Fixed by
  implementing ShipClass.GetShipProperty().

This loads real E1M2 end-to-end through the SDK loader (which applies the AST
transforms — the crash only reproduces through that path).
"""
from engine import host_loop
from tests.integration.test_sdk_bridge_load import _fresh_world

import App


E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _init_e1m2():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    return mod


def test_create_moving_asteroids_runs_without_crashing():
    mod = _init_e1m2()

    # Preconditions CreateMovingAsteroids checks before spawning.
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    assert pSet is not None
    assert App.ShipClass_GetObject(pSet, "Facility") is not None
    assert getattr(mod, "g_bMissionTerminate", 0) == 1

    # The regression: this used to raise
    # AttributeError: 'dict_keys' object has no attribute 'sort'.
    assert mod.CreateMovingAsteroids() == 0

    # It actually placed the asteroids (5 authored in g_dAsteroidInfo).
    assert len(mod.g_dAsteroidInfo) == 5


def test_asteroid_ship_property_and_death_sound_reachable():
    # Fix 2 at the seam Effects.GetDeathExplosionSound uses: GetShipProperty()
    # must return the real ShipProperty carrying the authored death sound, not a
    # _Stub. asteroid.py:34 sets SetDeathExplosionSound("g_lsDeathExplosions").
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()

    name = sorted(mod.g_dAsteroidInfo.keys())[0]
    pAsteroid = App.ShipClass_GetObject(pSet, name)
    assert pAsteroid is not None

    prop = pAsteroid.GetShipProperty()
    assert prop is not None
    sound = prop.GetDeathExplosionSound()
    assert isinstance(sound, str)
    assert sound == "g_lsDeathExplosions"


def test_asteroid_exploding_death_script_runs_without_typeerror():
    # The death script used to raise (swallowed) TypeError from a _Stub attribute
    # name inside Effects.GetDeathExplosionSound. Call it directly and assert it
    # completes — no exception.
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()

    name = sorted(mod.g_dAsteroidInfo.keys())[0]
    pAsteroid = App.ShipClass_GetObject(pSet, name)
    assert pAsteroid is not None

    mod.AsteroidExploding(pAsteroid)  # must not raise
