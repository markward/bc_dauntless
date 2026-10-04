"""Space dust x field_dust_mult inside rock fields (Mark, live 2026-10-03)."""
import pytest

from engine.rocks import density, far_dials, far_tier


@pytest.fixture(autouse=True)
def _clean():
    far_dials.reset()
    far_tier.reset()
    yield
    far_dials.reset()
    far_tier.reset()


def _sphere(radius=1000.0, edge=0.2, centre=(0.0, 0.0, 0.0)):
    return density.DiscSource(
        id=1, frame="Beol4", centre_gu=centre, normal=(0.0, 0.0, 1.0), table=[],
        outer_fade_gu=0.0, scale_height_frac=0.0, scale_height_min_gu=0.0,
        families={"silicate": 1.0}, seed=1, shape="sphere", procedural=False,
        view_space=True, sphere_radius_gu=radius, sphere_edge_frac=edge)


def test_sphere_strength_is_one_inside_ramps_at_the_edge_zero_outside():
    s = _sphere()
    assert far_tier.source_strength(s, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)) == 1.0
    assert far_tier.source_strength(s, (900.0, 0.0, 0.0), (0.0, 0.0, 0.0)) == pytest.approx(0.5)
    assert far_tier.source_strength(s, (1200.0, 0.0, 0.0), (0.0, 0.0, 0.0)) == 0.0


def test_dust_profile_lift_triples_density_at_full_strength():
    far_dials._dials["field_dust_mult"] = 3.0
    # density_mult = 1 + 9 * profile (DustPass::kMaxDensityMult = 10)
    lifted = far_tier.dust_profile_in_field(0.0, 1.0)
    assert 1.0 + 9.0 * lifted == pytest.approx(3.0)
    base = 0.1                                   # mult 1.9 -> 5.7
    assert 1.0 + 9.0 * far_tier.dust_profile_in_field(base, 1.0) == pytest.approx(5.7)
    assert far_tier.dust_profile_in_field(base, 0.0) == base
    assert far_tier.dust_profile_in_field(0.9, 1.0) == 1.0   # capped at x10
    assert far_tier.dust_profile_in_field(0.0, 0.5) == pytest.approx(lifted * 0.5)


def test_mult_of_one_is_off():
    far_dials._dials["field_dust_mult"] = 1.0
    assert far_tier.dust_profile_in_field(0.2, 1.0) == pytest.approx(0.2)
