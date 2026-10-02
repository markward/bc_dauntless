import math

import pytest

from engine.rocks import density, far_dials, field_table


def test_vesuvi_has_one_belt_centred_on_its_star():
    (s,) = density.sources_for_system("Vesuvi")
    assert s.frame == "Vesuvi"
    assert s.centre_gu == (0.0, 0.0, 0.0)
    assert s.normal == (0.0, 0.0, 1.0)
    assert density.table_a(s, 278000.0) == 0.5
    assert density.table_a(s, 100000.0) == 0.05


def test_systems_without_asteroids_have_no_belt():
    assert density.sources_for_system("Beol") == []
    assert density.sources_for_system("NoSuchSystem") == []


def test_outer_fade_past_the_last_row():
    (s,) = density.sources_for_system("Vesuvi")
    assert math.isclose(density.table_a(s, 350000.0), 0.025, rel_tol=1e-6)
    assert density.table_a(s, 360001.0) == 0.0


def test_vertical_falloff():
    (s,) = density.sources_for_system("Vesuvi")
    h = 0.03 * 278000.0
    assert math.isclose(density.evaluate(s, (278000.0, 0.0, h)),
                        0.5 * math.exp(-0.5), rel_tol=1e-6)


def test_table_longer_than_the_shader_is_truncated(capsys, monkeypatch):
    rows = [(float(i * 1000), 0.5) for i in range(40)]
    s = density.DiscSource(1, "X", (0, 0, 0), (0, 0, 1), rows, 0.0, 0.03, 1000.0,
                           {"silicate": 1.0}, 1)
    d = density.to_native(s)
    assert len(d["table"]) == density.MAX_TABLE_ROWS


def test_empty_table_builds_nothing():
    s = density.DiscSource(1, "X", (0, 0, 0), (0, 0, 1), [], 0.0, 0.03, 1000.0,
                           {"silicate": 1.0}, 1)
    assert density.table_a(s, 0.0) == 0.0


def test_populations_follow_the_roadmap_anchors():
    minor, major = field_table.populations()
    assert math.isclose(minor.density_at_1, 405 / (4.0 / 3.0 * math.pi * 1000.0 ** 3),
                        rel_tol=1e-3)
    assert math.isclose(major.density_at_1, 1.0 / 1.2e9)
    assert major.a_lo == 0.5 and minor.a_lo == 0.0


def test_to_native_resolves_families_to_catalogue_indices():
    (s,) = density.sources_for_system("Vesuvi")
    d = density.to_native(s)
    minor, major = d["populations"]
    assert minor["kind"] == 0 and major["kind"] == 1
    from engine.rocks import catalogue
    rocks = catalogue.load()
    assert all(rocks[i].kind == "fragment" and rocks[i].family == "silicate"
               for i in minor["rocks"])
    assert all(rocks[i].kind == "major" for i in major["rocks"])
    assert len(minor["weights"]) == len(minor["rocks"])


def test_to_native_drops_a_population_with_no_matching_rocks(monkeypatch, capsys):
    """A family with no matching catalogue rock of a population's kind must
    not reach native: pick_rock would render every generated rock of that
    population as catalogue index 0 regardless of kind/family."""
    from engine.rocks import catalogue

    class _FakeRock:
        def __init__(self, kind, family, avg_albedo=(0.4, 0.4, 0.4)):
            self.kind = kind
            self.family = family
            self.avg_albedo = avg_albedo

    (s,) = density.sources_for_system("Vesuvi")
    # Only a "major" silicate rock exists -- no "fragment" (minor) match.
    monkeypatch.setattr(catalogue, "load", lambda: (_FakeRock("major", "silicate"),))

    d = density.to_native(s)
    kinds = [p["kind"] for p in d["populations"]]
    assert kinds == [1]   # minor (kind 0) dropped, major (kind 1) kept

    err = capsys.readouterr().err
    assert err.count("[far]") == 1


# ── Tile-field sphere sources (added 2026-10-02) ─────────────────────────────


class _Loc:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Field:
    """The AsteroidField surface density.tile_field_source reads (Beol 4's
    numbers; engine/appc/asteroid_field.py)."""
    def __init__(self, name="Asteroid Field 1", loc=(797.714355, 977.248474, 1268.854858),
                 radius=1000.0, tiles=3, per_tile=15, size_factor=7.0):
        self._name, self._loc, self._r = name, loc, radius
        self._tiles, self._per, self._sf = tiles, per_tile, size_factor
    def GetName(self): return self._name
    def GetWorldLocation(self): return _Loc(*self._loc)
    def GetFieldRadius(self): return self._r
    def GetNumTilesPerAxis(self): return self._tiles
    def GetNumAsteroidsPerTile(self): return self._per
    def GetAsteroidSizeFactor(self): return self._sf


# Characterization (rock-fields Task 2): captured from the code BEFORE the
# tile minor clouds were removed. tile_haze_gain = 14140 was calibrated on
# exactly these numbers, so they must never drift.
EXPECTED_DENSITY = 9.668662792832643e-08     # 405 / (4/3 pi 1000^3)
EXPECTED_SIZES = (0.05, 0.7000000000000001, 2.5)
EXPECTED_SEED = 1807423987                   # crc32("tile:Beol4:Asteroid Field 1")


def test_tile_field_source_values_are_pinned(monkeypatch):
    from engine.rocks import minor_dials
    far_dials.reset(); minor_dials.reset()
    monkeypatch.setattr("engine.systems.frames.containing_set", lambda o: None)
    s = density.tile_field_source(_Field(), None, "Beol4", (0.0, 0.0, 0.0))
    (pop,) = s.pops
    assert s.shape == "sphere" and s.procedural is False and s.view_space is True
    assert s.centre_gu == (797.714355, 977.248474, 1268.854858)
    assert s.sphere_radius_gu == 1000.0
    assert pop.density_at_1 == pytest.approx(EXPECTED_DENSITY, rel=1e-12)
    assert (pop.r_min, pop.r_max, pop.exponent) == pytest.approx(EXPECTED_SIZES)
    assert s.seed == EXPECTED_SEED and s.id == EXPECTED_SEED & 0x7fffffff
    assert dict(pop.families) == {"silicate": 1.0} and s.families == {"silicate": 1.0}


def test_tile_field_source_centre_is_offset_into_view_space():
    s = density.tile_field_source(_Field(), None, "Beol4", (10.0, -20.0, 30.0))
    assert s.centre_gu == pytest.approx((807.714355, 957.248474, 1298.854858))


def test_tile_field_source_is_a_view_space_sphere():
    f = _Field()
    s = density.tile_field_source(f, None, "Beol4", (0.0, 0.0, 0.0))
    assert s.shape == "sphere" and s.procedural is False and s.view_space is True
    assert s.centre_gu == (797.714355, 977.248474, 1268.854858)
    assert s.sphere_radius_gu == 1000.0
    assert s.sphere_edge_frac == far_dials.get("tile_haze_edge_frac")
    assert math.isclose(s.gain_scale,
                        far_dials.get("tile_haze_gain") / far_dials.get("haze_gain"))
    assert s.brightness == far_dials.get("tile_haze_brightness")
    (pop,) = s.pops
    assert pop.kind == 0 and pop.a_lo == 0.0 and pop.a_hi == 1.0
    assert math.isclose(pop.density_at_1, 405 / (4.0 / 3.0 * math.pi * 1000.0 ** 3))
    assert pop.exponent == 2.5
    assert math.isclose(pop.r_max, 0.7) and pop.r_min == 0.05
    assert dict(pop.families) == {"silicate": 1.0}


def test_tile_field_source_follows_the_minor_dials():
    from engine.rocks import minor_dials
    minor_dials._dials = dict(minor_dials._dials, tile_count_mult=2.0)
    try:
        (pop,) = density.tile_field_source(_Field(), None, "Beol4", (0.0, 0.0, 0.0)).pops
    finally:
        minor_dials.reset()
    assert math.isclose(pop.density_at_1, 810 / (4.0 / 3.0 * math.pi * 1000.0 ** 3))


def test_an_empty_tile_field_has_no_source():
    assert density.tile_field_source(_Field(per_tile=0), None, "X", (0.0, 0.0, 0.0)) is None


def test_to_native_emits_the_sphere_keys_and_only_the_minor_population():
    s = density.tile_field_source(_Field(), None, "Beol4", (0.0, 0.0, 0.0))
    d = density.to_native(s)
    assert d["shape"] == "sphere" and d["procedural"] is False and d["view_space"] is True
    assert d["sphere_radius_gu"] == 1000.0 and d["sphere_edge_frac"] == 0.2
    assert d["gain_scale"] == s.gain_scale
    assert d["brightness"] == s.brightness == far_dials.get("tile_haze_brightness")
    assert d["centre"] == s.centre_gu and d["table"] == []
    (pop,) = d["populations"]
    assert pop["kind"] == 0 and pop["rocks"]


def test_a_belt_to_native_keeps_the_disc_defaults():
    (s,) = density.sources_for_system("Vesuvi")
    d = density.to_native(s)
    assert (d["shape"], d["procedural"], d["view_space"], d["gain_scale"]) == \
        ("disc", True, False, 1.0)


def test_a_belt_carries_the_belt_haze_brightness():
    (s,) = density.sources_for_system("Vesuvi")
    assert s.brightness == far_dials.get("haze_brightness")
    assert density.to_native(s)["brightness"] == far_dials.get("haze_brightness")


def test_a_tile_field_source_carries_the_noise_dials():
    s = density.tile_field_source(_Field(), None, "Beol4", (0.0, 0.0, 0.0))
    assert s.noise_scale_gu == far_dials.get("tile_haze_noise_scale_gu")
    assert s.noise_contrast == far_dials.get("tile_haze_noise_contrast")
    assert s.noise_octaves == far_dials.get("tile_haze_noise_octaves")
    assert s.steps == far_dials.get("tile_haze_steps")
    d = density.to_native(s)
    assert (d["noise_scale_gu"], d["noise_contrast"], d["noise_octaves"], d["steps"]) == \
        (250.0, 0.8, 3, 48)


def test_profile_belt_carries_belt_noise_dials():
    """Rock-fields R1 (2026-10-02): every source's density is a(x) * m(x),
    so a belt carries the belt noise dials, and to_native sends them."""
    far_dials.reset()
    (src,) = density.sources_for_system("Vesuvi")
    assert src.noise_scale_gu == far_dials.get("belt_noise_scale_gu")
    assert src.noise_contrast == far_dials.get("belt_noise_contrast")
    assert src.noise_octaves == far_dials.get("belt_noise_octaves")
    nat = density.to_native(src)
    assert nat["noise_scale_gu"] == src.noise_scale_gu   # now sent for discs too
    assert nat["noise_contrast"] == src.noise_contrast
    assert nat["noise_octaves"] == src.noise_octaves
    assert nat["steps"] == 0                               # the global haze_steps
