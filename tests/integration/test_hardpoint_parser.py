"""Hardpoint expectation extractor unit tests."""
import pytest

from engine import paths as _paths
from tests.integration._hardpoint_parser import extract_setters


SDK_HARDPOINTS = _paths.sdk_scripts() / "ships" / "Hardpoints"


def test_extract_galaxy_ship_mass():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "Galaxy")
    assert setters["Mass"] == 120.0
    assert setters["RotationalInertia"] == 15000.0
    assert setters["ShipName"] == "Dauntless"
    assert setters["AIString"] == "FedAttack"
    assert setters["Affiliation"] == 0
    assert setters["Stationary"] == 0


def test_extract_galaxy_hull_max_condition():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "Hull")
    assert setters["MaxCondition"] > 0


def test_extract_galaxy_impulse():
    setters = extract_setters(SDK_HARDPOINTS / "galaxy.py", "ImpulseEngines")
    assert setters["MaxSpeed"] == 6.3
    assert setters["MaxAccel"] == 1.5
    assert setters["MaxAngularVelocity"] == 0.28
    assert setters["MaxAngularAccel"] == 0.12


def test_extract_missing_template_raises():
    with pytest.raises(KeyError):
        extract_setters(SDK_HARDPOINTS / "galaxy.py", "NotPresent")
