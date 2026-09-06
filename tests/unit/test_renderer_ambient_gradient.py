"""engine.renderer directional-ambient wrappers forward to the host module."""
from unittest.mock import MagicMock

import pytest

import engine.renderer as renderer


def test_set_ambient_gradient_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_ambient_gradient(0.25)
    fake.ambient_gradient_set.assert_called_once_with(0.25)


def test_set_ambient_gradient_coerces_to_float(monkeypatch):
    # The knob is driven from the dev console and from tuning scripts, so an
    # int is a realistic input; pybind11 rejects the wrong type outright.
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_ambient_gradient(1)
    fake.ambient_gradient_set.assert_called_once_with(1.0)


def test_ambient_gradient_reads_back(monkeypatch):
    fake = MagicMock()
    fake.ambient_gradient_get.return_value = 0.6
    monkeypatch.setattr(renderer, "_h", fake)
    assert renderer.ambient_gradient() == pytest.approx(0.6)


def test_default_is_biased_high_for_the_first_live_look():
    """0.6, not something subtle. The house practice is to calibrate UP and
    then come down; a first pass too faint to see wastes the live check."""
    host = pytest.importorskip("_dauntless_host")
    assert host.ambient_gradient_get() == pytest.approx(0.6)


def test_out_of_range_values_are_clamped_not_rejected():
    """The shader term goes negative past 1.0, which would subtract ambient
    on the far side. Clamp rather than trust the caller."""
    host = pytest.importorskip("_dauntless_host")
    original = host.ambient_gradient_get()
    try:
        host.ambient_gradient_set(5.0)
        # ambient_gradient_get reports the GATE's budget, not the resolved
        # per-frame strength (which is additionally scaled by how coherent the
        # set's lights are). Keep the two distinct.
        assert host.ambient_gradient_get() == pytest.approx(1.0)
        host.ambient_gradient_set(-1.0)
        assert host.ambient_gradient_get() == pytest.approx(0.0)
    finally:
        host.ambient_gradient_set(original)
