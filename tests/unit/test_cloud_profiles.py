"""Shape tests for engine/systems/clouds.py -- the three cloud profiles.

debris and nebula must carry BC's authored numbers verbatim; the cross-check
against the real SDK lives in tests/tools/test_system_survey.py, not here.
"""
import pytest

from engine.systems import clouds


def test_bc_profile_numbers():
    assert clouds.params_for("debris") == {
        "visibility_gu": 145.0, "sensor_density": 10.5,
        "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0}
    assert clouds.params_for("nebula") == {
        "visibility_gu": 200.0, "sensor_density": 6.5,
        "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def test_mist_is_declared_and_inert():
    """Named in the design, numbers deferred. Zeroed means it renders and does
    nothing, which is the behaviour this change ships."""
    assert clouds.params_for("mist") == {
        "visibility_gu": 0.0, "sensor_density": 0.0,
        "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def test_params_for_returns_a_copy():
    clouds.params_for("debris")["damage_hull_per_s"] = 1.0
    assert clouds.params_for("debris")["damage_hull_per_s"] == 150.0


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        clouds.params_for("fog")
