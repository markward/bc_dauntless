import App
from tests.integration.test_sdk_bridge_load import _fresh_world


def test_multi1_places_54_distinct_rocks():
    from engine.rocks.rock import is_rock
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = [pSet.GetObject("Asteroid %d" % i) for i in range(1, 55)]
    assert all(r is not None and is_rock(r) for r in rocks)
    pts = {(round(r.GetWorldLocation().x, 3), round(r.GetWorldLocation().y, 3),
            round(r.GetWorldLocation().z, 3)) for r in rocks}
    assert len(pts) == 54
