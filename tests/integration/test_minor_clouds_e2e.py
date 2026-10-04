"""Minor clouds from REAL SDK content (minor-rocks spec §5 E2E): the SDK's
own system modules place the rocks and AsteroidFields; the registry turns
them into clouds with the spec's counts. AsteroidFields get none (rock-fields)."""
import App
from engine.rocks import minors
from tests.integration.test_sdk_bridge_load import _fresh_world


def _fields(pSet):
    return [App.AsteroidField_Cast(o)
            for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]


def _tile_keys(specs):
    return [k for k in specs if k.startswith("tile:")]


def test_beol4_asteroid_field_gets_no_minor_cloud():
    """Rock-fields (2026-10-02): a BC AsteroidField is a far-tier density
    source (engine/rocks/density.py:tile_field_source), never a tile cloud."""
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    assert len(_fields(pSet)) == 1
    specs = minors.desired_clouds(pSet, rock_instances={}, fields=_fields(pSet))
    assert _tile_keys(specs) == []


def test_multi1_registers_54_halos():
    from engine.rocks.rock import is_rock
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = {pSet.GetObject("Asteroid %d" % i): i for i in range(1, 55)}
    assert all(is_rock(r) for r in rocks)
    specs = minors.desired_clouds(pSet, rock_instances=rocks, fields=_fields(pSet))
    assert sum(1 for k in specs if k.startswith("halo:")) == 54
    assert "halo:Multi1:Asteroid 1" in specs      # set-qualified halo keys
    assert _tile_keys(specs) == []
