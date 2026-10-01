import pytest

from engine.rocks import minor_dials as md


@pytest.fixture(autouse=True)
def _fresh():
    md.reset()
    yield
    md.reset()


def test_spec_defaults():
    d = md.DEFAULTS
    assert d["halo_inner"] == 1.1 and d["halo_outer"] == 3.0
    assert d["halo_min"] == 12 and d["halo_max"] == 400
    assert d["halo_r_min_gu"] == 0.03 and d["halo_r_max_frac"] == 0.15
    assert d["halo_r_max_gu"] == 1.0
    assert d["tile_count_mult"] == 1.0 and d["tile_r_min_gu"] == 0.05
    assert d["tile_r_per_size_factor"] == 0.1
    assert d["max_debris_per_death"] == 40 and d["max_live_minors"] == 20000
    assert d["min_pixel_radius"] == 1.5 and d["lod0_pixel_radius"] == 24.0
    assert d["contact_margin_gu"] == 0.1 and d["shove_transfer"] == 0.6
    assert d["shove_min_gu"] == 0.3 and d["shove_damp_seconds"] == 4.0
    assert d["max_shoves_per_frame"] == 64 and d["teleport_gu"] == 20000.0
    assert d["debris_damp_seconds"] == 6.0
    assert d["cloud_fade_in_seconds"] == 1.5
    assert d["free_cloud_fade_seconds"] == 2.0
    assert d["puff_max_per_s"] == 6 and d["grit_max_per_s"] == 4
    assert d["flicker_max_per_s"] == 2 and d["flicker_intensity"] == 0.3


def test_native_keys_are_a_subset_and_native_filters():
    assert md.NATIVE_KEYS <= set(md.DEFAULTS)
    assert set(md.native()) == md.NATIVE_KEYS


def test_every_dial_is_in_the_cycle_order():
    assert set(md.DIAL_ORDER) == set(md.DEFAULTS)


def test_step_is_pure_and_multiplicative_for_floats():
    d0 = md.current()
    d1 = md.step(d0, "halo_outer", +1)
    assert d0["halo_outer"] == 3.0
    assert d1["halo_outer"] == pytest.approx(3.0 * 1.25)


def test_step_counts_are_ints_and_clamped():
    d = md.step(md.current(), "halo_min", -1)
    assert isinstance(d["halo_min"], int) and d["halo_min"] >= 0
    d = md.current()
    for _ in range(50):
        d = md.step(d, "max_shoves_per_frame", -1)
    assert d["max_shoves_per_frame"] >= 1


def test_registered_group_steps_and_notifies():
    import engine.dev_dial_groups as g
    g.reset()
    seen = []
    md.set_on_change(lambda names: seen.append(names))
    md.register()
    assert "minors" in g.groups()
    while g.active() != "minors":
        g.cycle_active()
    g.push(+1)
    assert seen == [{md.DIAL_ORDER[0]}]
    assert md.get(md.DIAL_ORDER[0]) != md.DEFAULTS[md.DIAL_ORDER[0]]
    g.reset()


def test_family_index():
    assert md.FAMILY_INDEX == {"silicate": 0, "carbonaceous": 1,
                               "icy": 2, "metallic": 3}
