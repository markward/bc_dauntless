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


# E3M2_Vesuvi4_P.py places the "Berkeley Start" waypoint at this set-local
# offset; Vesuvi 4's region anchor sits at (0, 122000, 0) from the star.
_BERKELEY_START_LOCAL = (-17.990969, -52.041687, -11.675355)


def _vesuvi_berkeley_start():
    import math
    from engine.systems import map as M
    m = M.load("vesuvi")
    star = next(b for b in m.bodies if b.orbits is None)
    ax, ay, az = m.regions[0].anchor_gu
    lx, ly, lz = _BERKELEY_START_LOCAL
    r = math.dist((ax + lx, ay + ly, az + lz), tuple(star.position_gu))
    return m.profile, r


def test_profile_alone_never_breaks_lock_at_e3m2_berkeley_start(monkeypatch):
    # Final review #1: sensors(r) * C_V reached >= LOCK_BREAK_T across the
    # Vesuvi cloud band, making E3M2's ships and the player mutually blind.
    prof, r = _vesuvi_berkeley_start()
    assert P.evaluate(prof, r).sensors * prof.full_concealment \
        >= sensor_detection.LOCK_BREAK_T   # the uncapped term would break lock
    monkeypatch.setattr(P, "locate", lambda obj: (prof, r))
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.0)
    assert sensor_detection.concealment_at(object()) < sensor_detection.LOCK_BREAK_T


def test_profile_at_full_sensors_stays_below_lock_break(monkeypatch):
    monkeypatch.setattr(P, "locate", lambda obj: (
        P.Profile(rows=[P.ProfileRow(0.0, sensors=1.0)], full_concealment=0.9), 0.0))
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.0)
    assert sensor_detection.concealment_at(object()) < sensor_detection.LOCK_BREAK_T


def test_local_fbm_at_lock_break_still_wins_over_the_capped_profile(monkeypatch):
    prof, r = _vesuvi_berkeley_start()
    monkeypatch.setattr(P, "locate", lambda obj: (prof, r))
    local = sensor_detection.LOCK_BREAK_T + 0.05
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: local)
    assert sensor_detection.concealment_at(object()) == pytest.approx(local)


def test_developer_conceal_cap_dial_overrides_the_constant(monkeypatch):
    from engine import dev_mode, dev_nebula_dials
    monkeypatch.setattr(P, "locate", lambda obj: (_prof(1.0), 1000.0))
    monkeypatch.setattr(sensor_detection, "_local_concealment", lambda ship: 0.0)
    monkeypatch.setattr(dev_nebula_dials, "_dials",
                        dict(dev_nebula_dials.DEFAULTS, conceal_cap=0.15))
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    assert sensor_detection.concealment_at(object()) == pytest.approx(0.15)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    assert sensor_detection.concealment_at(object()) == pytest.approx(
        sensor_detection.PROFILE_CONCEALMENT_CAP)
