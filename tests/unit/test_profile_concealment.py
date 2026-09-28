import pytest

from engine.appc import sensor_detection
from engine.systems import profile as P


def _prof(sensors):
    return P.Profile(rows=[P.ProfileRow(0.0, sensors=sensors)], full_concealment=0.4)


def test_profile_concealment_applies_with_no_local_nebula(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.5), 1000.0))
    ship = type("S", (), {})()
    assert sensor_detection.concealment_at(ship) == pytest.approx(0.2)


def test_the_larger_of_local_and_profile_wins(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(0.25), 1000.0))
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.3)
    assert sensor_detection.concealment_at(object()) == pytest.approx(0.3)
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.05)
    assert sensor_detection.concealment_at(object()) == pytest.approx(0.1)


def test_unmapped_object_gets_no_profile_concealment(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: None)
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.0)
    assert sensor_detection.concealment_at(object()) == 0.0
