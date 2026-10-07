"""Per-instance planet atmosphere state (spec 2026-10-07).

`set_instance_atmosphere(iid, params)` stores a disabled
`scenegraph::Instance::Atmosphere` (`params=None`) or an enabled one built from
an `engine.planets.atmosphere.Atmosphere`, on the native instance. The
test-only `_h.atmosphere_debug(iid)` reads it back as
`(color, sunset_color, thickness, density, limb, intensity, mie)` or `None` when
disabled — later tasks read `inst.atmosphere` straight off the renderer's own
`scenegraph::Instance`, so this binding only needs to prove the round trip.

`intensity` (shell-halo brightness multiplier only, default 20.0) travels as an
OPTIONAL 6th tuple element on the raw `_h.set_instance_atmosphere` call — a
5-tuple (the pre-intensity shape) must still default to 20.0 so an older
caller is unaffected. `mie` (grey Mie strength, default 0.2) is likewise an
OPTIONAL 7th element; 5- and 6-tuples keep 0.2.
"""
import pytest

pytest.importorskip("_dauntless_host")

import engine.renderer as r  # noqa: E402


def test_binding_is_present():
    """A stale build would silently drop the whole feature — assert it loudly."""
    assert hasattr(r._h, "set_instance_atmosphere")
    assert hasattr(r._h, "atmosphere_debug")


def test_set_instance_atmosphere_round_trips():
    from engine.planets.atmosphere import Atmosphere

    iid = r.create_instance(0)
    try:
        assert r._h.atmosphere_debug(iid) is None

        r.set_instance_atmosphere(
            iid, Atmosphere((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0))
        color, sunset, thickness, density, limb, intensity, mie = r._h.atmosphere_debug(iid)
        assert color == pytest.approx((1.0, 0.5, 0.25))
        assert sunset == pytest.approx((0.9, 0.4, 0.2))
        assert thickness == pytest.approx(0.06)
        assert density == pytest.approx(1.4)
        assert limb == pytest.approx(1.0)
        assert intensity == pytest.approx(20.0)   # Atmosphere's own default
        assert mie == pytest.approx(0.2)          # Atmosphere's own default

        r.set_instance_atmosphere(iid, None)
        assert r._h.atmosphere_debug(iid) is None
    finally:
        r.destroy_instance(iid)


def test_wrapper_passes_explicit_intensity():
    from engine.planets.atmosphere import Atmosphere

    iid = r.create_instance(0)
    try:
        r.set_instance_atmosphere(
            iid, Atmosphere((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0,
                            intensity=20.0))
        *_, intensity, _mie = r._h.atmosphere_debug(iid)
        assert intensity == pytest.approx(20.0)
    finally:
        r.destroy_instance(iid)


def test_wrapper_passes_mie():
    from engine.planets.atmosphere import Atmosphere

    iid = r.create_instance(0)
    try:
        r.set_instance_atmosphere(
            iid, Atmosphere((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0,
                            intensity=20.0, mie=0.65))
        *_, mie = r._h.atmosphere_debug(iid)
        assert mie == pytest.approx(0.65)
    finally:
        r.destroy_instance(iid)


def test_raw_binding_5_tuple_defaults_intensity_to_twenty():
    """Backward compatibility: a caller built before `intensity` existed that
    still hands the binding a bare 5-tuple must not regress."""
    iid = r.create_instance(0)
    try:
        r._h.set_instance_atmosphere(
            iid, ((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0))
        *_, intensity, mie = r._h.atmosphere_debug(iid)
        assert intensity == pytest.approx(20.0)
        assert mie == pytest.approx(0.2)
    finally:
        r.destroy_instance(iid)


def test_raw_binding_6_tuple_carries_intensity():
    iid = r.create_instance(0)
    try:
        r._h.set_instance_atmosphere(
            iid, ((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0, 33.0))
        *_, intensity, mie = r._h.atmosphere_debug(iid)
        assert intensity == pytest.approx(33.0)
        assert mie == pytest.approx(0.2)
    finally:
        r.destroy_instance(iid)


def test_raw_binding_7_tuple_carries_mie():
    iid = r.create_instance(0)
    try:
        r._h.set_instance_atmosphere(
            iid, ((1.0, 0.5, 0.25), (0.9, 0.4, 0.2), 0.06, 1.4, 1.0, 33.0, 1.25))
        *_, intensity, mie = r._h.atmosphere_debug(iid)
        assert intensity == pytest.approx(33.0)
        assert mie == pytest.approx(1.25)
    finally:
        r.destroy_instance(iid)


def test_atmosphere_debug_unknown_instance_raises():
    iid = r.create_instance(0)
    r.destroy_instance(iid)
    with pytest.raises(ValueError):
        r._h.atmosphere_debug(iid)
