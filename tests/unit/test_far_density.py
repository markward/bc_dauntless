import math
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
