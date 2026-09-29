"""Hull sparks and impulse trails follow the radial profile, not only BC's
local clump (Mark, 2026-09-29: sparks represent radiation)."""
import pytest

from engine.systems import profile_fx as fx
from engine.systems.profile import Sample


def test_sparks_follow_the_radiation_level_outside_any_clump():
    active, rate = fx.discharge_inputs(False, 0.0, Sample(radiation=0.4), warping=False)
    assert active is True
    assert rate == pytest.approx(150.0 * 0.4)


def test_sparks_take_the_stronger_of_clump_and_profile():
    assert fx.discharge_inputs(True, 150.0, Sample(radiation=0.4), False) == (True, 150.0)
    assert fx.discharge_inputs(True, 10.0, Sample(radiation=0.4), False)[1] == pytest.approx(60.0)


def test_no_sparks_in_clear_space_or_while_dashing():
    assert fx.discharge_inputs(False, 0.0, Sample(), False) == (False, 0.0)
    assert fx.discharge_inputs(False, 0.0, Sample(radiation=1.0), True) == (False, 0.0)


def test_a_clump_still_sparks_on_its_own():
    assert fx.discharge_inputs(True, 150.0, Sample(), False) == (True, 150.0)


def test_trails_follow_the_nebula_column_at_its_floor():
    assert fx.wake_active(False, Sample(nebula=0.05), False) is True
    assert fx.wake_active(False, Sample(nebula=0.049), False) is False
    assert fx.wake_active(True, Sample(), False) is True
    assert fx.wake_active(False, Sample(nebula=1.0), True) is False


def test_lightning_fires_in_the_profiles_thick_cloud():
    assert fx.LIGHTNING_NEBULA_MIN == 0.5
    assert fx.lightning_active(False, Sample(nebula=0.5), False) is True
    assert fx.lightning_active(False, Sample(nebula=0.499), False) is False


def test_lightning_fires_in_a_clump_alone_and_never_while_dashing():
    assert fx.lightning_active(True, Sample(), False) is True
    assert fx.lightning_active(True, Sample(nebula=1.0), True) is False
    assert fx.lightning_active(False, Sample(nebula=1.0), True) is False



def test_star_godray_intensity_is_gain_times_gas_times_transmittance():
    assert fx.star_godray_intensity(1.0, Sample(), 1.0) == 0.0
    assert fx.star_godray_intensity(1.0, Sample(nebula=1.0), 0.0) == 0.0
    assert fx.star_godray_intensity(2.0, Sample(nebula=0.5), 0.4) == pytest.approx(0.4)
    assert (fx.star_godray_intensity(1.0, Sample(nebula=0.8), 0.5)
            > fx.star_godray_intensity(1.0, Sample(nebula=0.2), 0.5))
