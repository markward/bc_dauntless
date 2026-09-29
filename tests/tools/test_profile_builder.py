import pytest

from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap
from tools.systems import profile_builder as B

V4 = {"color": (0.6, 0.35, 0.72), "spheres": [(0.0, 1500.0, 0.0, 1500.0)],
      "visibility_gu": 145.0, "sensor_density": 10.5,
      "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0}
B1 = {"color": (0.39, 0.39, 0.57), "spheres": [(-17.1, 844.7, -30.3, 900.0)],
      "visibility_gu": 200.0, "sensor_density": 6.5,
      "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def _vesuvi_like():
    return SystemMap(
        system="Vesuvi",
        bodies=[Body("Vesuvi", "Vesuvi", 2000.0, (0.0, 0.0, 0.0))],
        regions=[Region("Vesuvi4", (0.0, 122000.0, 0.0), 3566.8, nebula=V4),
                 Region("Vesuvi5", (229468.0, 0.0, 0.0), 13301.0)])


def test_visibility_fit_hits_both_campaign_samples():
    assert B.nebula_intensity(145.0) == pytest.approx(1.0)
    assert B.nebula_intensity(200.0) == pytest.approx(6.5 / 10.5, abs=1e-3)


def test_full_concealment_is_vesuvi_4s_measured_core():
    assert B.FULL_CONCEALMENT == pytest.approx(B.core_concealment(B.VESUVI_4_SPHERES))
    assert 0.0 < B.FULL_CONCEALMENT <= 1.0


def test_star_rows_are_one_at_the_surface_and_zero_at_three_radii():
    prof = P.Profile(rows=B.star_rows(2000.0))
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert P.evaluate(prof, 2000.0).radiation == 1.0
    assert P.evaluate(prof, 4000.0).radiation == pytest.approx(0.5)
    assert P.evaluate(prof, 6000.0).radiation == 0.0
    assert P.evaluate(prof, 1.0e6).radiation == 0.0


def test_cloud_rows_peak_at_the_clump_radius():
    rows = B.cloud_rows(_vesuvi_like().regions[0], (0.0, 0.0, 0.0), B.FULL_CONCEALMENT)
    prof = P.Profile(rows=rows)
    peak = P.evaluate(prof, 123500.0)
    assert (peak.nebula, peak.dust, peak.radiation) == (
        pytest.approx(1.0), pytest.approx(1.0), pytest.approx(1.0))
    assert peak.sensors == pytest.approx(1.0)
    assert P.evaluate(prof, 61750.0).nebula == 0.0            # rise starts at 0.5 R
    assert P.evaluate(prof, 247000.0).nebula == pytest.approx(0.05)  # floor at 2 R
    assert P.evaluate(prof, 1.0e7).nebula == pytest.approx(0.05)     # persists
    band = 2 * 3566.8
    assert P.evaluate(prof, 123500.0 + band).radiation == 0.0
    assert P.evaluate(prof, 123500.0 - band).sensors == 0.0
    assert P.evaluate(prof, 1.0e7).radiation == 0.0


def test_belaruz_cloud_has_an_authored_zero_radiation():
    region = Region("Belaruz1", (128000.0, 0.0, 0.0), 2229.6, nebula=B1)
    prof = P.Profile(rows=B.cloud_rows(region, (0.0, 0.0, 0.0), B.FULL_CONCEALMENT))
    r = P.clump_radius(region, (0.0, 0.0, 0.0))
    assert P.evaluate(prof, r).radiation == 0.0
    assert P.evaluate(prof, r).nebula == pytest.approx(6.5 / 10.5, abs=1e-3)


def test_compose_max_is_exact_across_crossings():
    a = [P.ProfileRow(0.0, radiation=1.0), P.ProfileRow(100.0, radiation=0.0)]
    b = [P.ProfileRow(0.0, radiation=0.0), P.ProfileRow(100.0, radiation=1.0)]
    prof = P.Profile(rows=B.compose_max(a, b))
    for r in (0.0, 25.0, 50.0, 75.0, 100.0):
        assert P.evaluate(prof, r).radiation == pytest.approx(max(1 - r / 100, r / 100))


def test_campaign_system_gets_cloud_plus_star():
    prof = B.build_profile(_vesuvi_like(), None, campaign=True)
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert P.evaluate(prof, 123500.0).nebula == pytest.approx(1.0)
    assert prof.color == V4["color"]
    assert prof.full_concealment == pytest.approx(B.FULL_CONCEALMENT)


def test_multi_system_gets_only_the_star_term():
    prof = B.build_profile(_vesuvi_like(), None, campaign=False)
    assert P.evaluate(prof, 123500.0) == P.CLEAR
    assert P.evaluate(prof, 0.0).radiation == 1.0
    assert prof.color is None


def test_override_replaces_derived_rows_and_keeps_the_star_term():
    override = {"rows": [{"distance_gu": 0.0, "dust": 0.1, "radiation": 0.4},
                         {"distance_gu": 500000.0, "dust": 0.1}]}
    prof = B.build_profile(_vesuvi_like(), override, campaign=True)
    assert P.evaluate(prof, 123500.0).nebula == 0.0          # derived rows gone
    assert P.evaluate(prof, 1000.0).radiation == 1.0         # star term on top
    assert P.evaluate(prof, 10000.0).radiation == pytest.approx(0.4 - 0.4 * 10000 / 500000)
    assert prof.color == V4["color"]
