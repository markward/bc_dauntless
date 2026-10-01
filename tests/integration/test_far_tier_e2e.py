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
