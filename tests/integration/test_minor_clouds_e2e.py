"""Minor clouds from REAL SDK content (minor-rocks spec §5 E2E): the SDK's
own system modules place the rocks and AsteroidFields; the registry turns
them into clouds with the spec's counts (BC tile fields table, spec "Facts")."""
import App
from engine.rocks import minors
from tests.integration.test_sdk_bridge_load import _fresh_world


def _fields(pSet):
    return [App.AsteroidField_Cast(o)
            for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]


def _tile_counts(specs):
    return sorted(s.count for k, s in specs.items() if k.startswith("tile:"))


def test_beol4_registers_a_405_minor_tile_cloud():
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    specs = minors.desired_clouds(pSet, rock_instances={}, fields=_fields(pSet))
    tiles = [s for k, s in specs.items() if k.startswith("tile:")]
    assert len(tiles) == 1 and tiles[0].count == 405
    assert tiles[0].key == "tile:Beol4:Asteroid Field 1"
    assert tiles[0].shell_outer == 1000.0


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
    assert _tile_counts(specs) == []          # Multi1's field is commented out


def test_vesuvi1_and_multi7_fields():
    _fresh_world()
    import Systems.Vesuvi.Vesuvi1 as v1
    v1.Initialize()
    pSet = v1.GetSet()
    assert _tile_counts(minors.desired_clouds(pSet, {}, _fields(pSet))) == [54]

    _fresh_world()
    import Systems.Multi7.Multi7 as m7     # its Initialize runs Multi7_S
    m7.Initialize()
    pSet = m7.GetSet()
    assert _tile_counts(minors.desired_clouds(pSet, {}, _fields(pSet))) == [54, 54, 54]


def test_reconcile_sends_the_beol4_tile_cloud_to_the_renderer():
    """Through reconcile_with (the per-frame core), not just the pure diff."""
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    added = []

    class _R:
        def minors_enabled(self): return True
        def minors_add_cloud(self, d): added.append(d)
        def __getattr__(self, n): return lambda *a, **k: 1
    minors.reconcile_with(_R(), pSet, {}, _fields(pSet), None)
    (d,) = added
    assert d["anchor"] == "point" and d["count"] == 405 and d["fade_in"] is False
