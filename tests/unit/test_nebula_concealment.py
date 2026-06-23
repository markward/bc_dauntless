"""Tactical concealment in the AI detection gate — TDD test suite.

Tests are written against the REAL can_detect(observer, target) signature
(no base_range= param). Fake ships have GetWorldLocation() + GetContainingSet()
so _get_xyz and concealment_at can both resolve position.

Sensor-less fixtures get FALLBACK_RANGE_GU = 30000 GU, so a few-hundred-GU
gap is always within range; RANGE is not the limiter and these tests cleanly
isolate the concealment mechanics.
"""
import App
from engine.appc import sensor_detection as sd


class _Ship:
    def __init__(self, name, x, y, z, set_):
        self._n, self._x, self._y, self._z, self._s = name, x, y, z, set_

    def GetName(self):
        return self._n

    def GetWorldLocation(self):
        return App.TGPoint3(self._x, self._y, self._z)

    def GetContainingSet(self):
        return self._s


def _set_with_dense_nebula():
    """A set containing one sphere-nebula at the origin (r=200 GU).

    Dials: gain=3.0, floor=0.0 → even moderate fbm output exceeds the
    LOCK_BREAK_T=0.6 threshold at the sphere centre.
    """
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.5, 0.5, 0.7, 145.0, 1.0, "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 200.0)
    # High gain + zero floor → dense at the core
    n.SetFbmDials(0.02, 3.0, 0.0)
    s.AddObjectToSet(n, "neb")
    return s, n


def test_concealment_zero_outside_nebula():
    """A ship far outside any nebula sphere has zero concealment."""
    s, n = _set_with_dense_nebula()
    ship = _Ship("P", 5000.0, 0.0, 0.0, s)   # far outside (sphere r=200)
    assert sd.concealment_at(ship) == 0.0


def test_concealment_high_in_dense_core():
    """A ship at the sphere centre gets high concealment (>0.5)."""
    s, n = _set_with_dense_nebula()
    ship = _Ship("P", 0.0, 0.0, 0.0, s)       # dead centre
    assert sd.concealment_at(ship) > 0.5


def test_can_detect_blocked_when_target_concealed():
    """A deeply-concealed target at point-blank range cannot be detected.

    Both ships have no sensor subsystem (FALLBACK_RANGE_GU=30000 GU), so
    range is not the reason detection fails — concealment is.
    """
    s, n = _set_with_dense_nebula()
    # Ensure the hysteresis latch is clean for this pair.
    sd._broken.clear()
    observer = _Ship("E", 0.0, 0.0, 300.0, s)
    hidden = _Ship("P", 0.0, 0.0, 0.0, s)     # in the dense core
    assert sd.can_detect(observer, hidden) is False


def test_can_detect_succeeds_in_clear_space():
    """Two ships well outside the nebula sphere can detect each other."""
    s, n = _set_with_dense_nebula()
    sd._broken.clear()
    observer = _Ship("E", 0.0, 0.0, 5300.0, s)
    visible = _Ship("P", 0.0, 0.0, 5000.0, s)  # both far outside (sphere r=200)
    assert sd.can_detect(observer, visible) is True
