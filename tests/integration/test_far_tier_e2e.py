"""Far tier from REAL SDK content (far-tier spec §5 E2E)."""
import App
from engine import host_loop
from engine.rocks import density, far_tier
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def test_e1m2_vesuvi_region_is_in_the_vesuvi_belt_frame():
    # E1M2 plays in Vesuvi 6, a mapped region of the Vesuvi system: loading
    # the mission runs Systems.Vesuvi.Vesuvi6.Initialize(), which the region
    # hook marks mapped (engine/systems/region_hooks.py).
    _fresh_world()
    host_loop._init_mission(E1M2_MODULE)
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    assert pSet is not None
    system, anchor = far_tier.frame_for(pSet)
    assert system == "Vesuvi"
    from engine.systems import resolve
    assert anchor == tuple(float(c) for c in resolve.anchor_of("Vesuvi6"))
    (src,) = density.sources_for_system(system)
    assert density.to_native(src)["populations"][0]["rocks"]


def test_multi1_rocks_are_flagged_with_catalogue_indices():
    from engine.rocks.rock import is_rock, rock_model_override
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = {pSet.GetObject("Asteroid %d" % i): i for i in range(1, 55)}
    assert all(is_rock(r) for r in rocks)
    for rock in rocks:
        path, scale = rock_model_override(rock)
        far_tier.note_model(rock, path, scale)
    flagged = far_tier.desired_rocks(rocks)
    assert len(flagged) == 54
    assert all(f["index"] >= 0 and f["radius_mu"] > 0.0 for f in flagged)
    assert far_tier.frame_for(pSet)[0] is None      # Multi1: one-set frame, no belt


def test_beol4_has_no_belt_source():
    assert density.sources_for_system("Beol") == []


# ── Tile-field haze from REAL SDK content (added 2026-10-02) ─────────────────


def _fields(pSet):
    return [App.AsteroidField_Cast(o)
            for o in pSet.GetClassObjectList(App.CT_ASTEROID_FIELD)]


class _Rec:
    def __init__(self):
        self.sources = []
    def far_set_sources(self, s):
        self.sources.append(s)
    def __getattr__(self, n):
        return lambda *a, **k: True


def test_beol4_field_hazes_as_one_sphere_where_the_gain_was_derived():
    """The tile gain was derived (far_field_test.cc) from Player Start toward
    this field: pin that the SDK still puts both where the derivation says."""
    _fresh_world()
    import Systems.Beol.Beol4 as beol4
    beol4.Initialize()
    pSet = beol4.GetSet()
    r = _Rec()
    far_tier.reconcile_with(r, pSet, {}, _fields(pSet))
    (pushed,) = r.sources
    (d,) = [s for s in pushed if s["shape"] == "sphere"]
    assert d["view_space"] is True and d["procedural"] is False
    assert d["sphere_radius_gu"] == 1000.0
    for got, want in zip(d["centre"], (797.714355, 977.248474, 1268.854858)):
        assert abs(got - want) < 1e-3
    (pop,) = d["populations"]
    import math
    assert math.isclose(pop["density_at_1"], 405 / (4.0 / 3.0 * math.pi * 1.0e9))
    assert math.isclose(pop["r_max"], 0.7) and pop["rocks"]
    start = pSet.GetObject("Player Start")
    assert start is not None
    loc = start.GetWorldLocation()
    for got, want in zip((loc.x, loc.y, loc.z), (-593.717346, 840.869934, -269.268738)):
        assert abs(got - want) < 1e-3


def test_vesuvi1_and_multi7_fields_haze():
    _fresh_world()
    import Systems.Vesuvi.Vesuvi1 as v1
    v1.Initialize()
    pSet = v1.GetSet()
    spheres = far_tier.tile_sources(pSet, _fields(pSet))
    assert len(spheres) == 1 and spheres[0].pops[0].density_at_1 > 0.0

    _fresh_world()
    far_tier.reset()
    import Systems.Multi7.Multi7 as m7     # its Initialize runs Multi7_S
    m7.Initialize()
    pSet = m7.GetSet()
    assert far_tier.frame_for(pSet)[0] is None     # unmapped: no belt, still haze
    r = _Rec()
    far_tier.reconcile_with(r, pSet, {}, _fields(pSet))
    (pushed,) = r.sources
    assert [s["shape"] for s in pushed] == ["sphere"] * 3
    assert len({s["id"] for s in pushed}) == 3
