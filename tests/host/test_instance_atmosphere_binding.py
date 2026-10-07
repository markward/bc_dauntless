"""Per-instance planet atmosphere state (spec 2026-10-07).

`set_instance_atmosphere(iid, params)` stores a disabled
`scenegraph::Instance::Atmosphere` (`params=None`) or an enabled one built from
an `engine.planets.atmosphere.Atmosphere`, on the native instance. The
test-only `_h.atmosphere_debug(iid)` reads it back as
`(color, sunset_color, thickness, density, limb)` or `None` when disabled —
later tasks read `inst.atmosphere` straight off the renderer's own
`scenegraph::Instance`, so this binding only needs to prove the round trip.
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
        color, sunset, thickness, density, limb = r._h.atmosphere_debug(iid)
        assert color == pytest.approx((1.0, 0.5, 0.25))
        assert sunset == pytest.approx((0.9, 0.4, 0.2))
        assert thickness == pytest.approx(0.06)
        assert density == pytest.approx(1.4)
        assert limb == pytest.approx(1.0)

        r.set_instance_atmosphere(iid, None)
        assert r._h.atmosphere_debug(iid) is None
    finally:
        r.destroy_instance(iid)


def test_atmosphere_debug_unknown_instance_raises():
    iid = r.create_instance(0)
    r.destroy_instance(iid)
    with pytest.raises(ValueError):
        r._h.atmosphere_debug(iid)
