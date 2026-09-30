import App
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
