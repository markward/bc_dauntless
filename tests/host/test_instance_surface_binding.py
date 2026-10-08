"""Per-instance planet surface-detail state (spec 2026-10-08).

`set_instance_surface(iid, params)` stores a default (type 0, "no detail")
`scenegraph::Instance::Surface` (`params=None`) or one built from the 8-tuple
`engine.planets.surface.to_binding` produces, on the native instance. Mirrors
`tests/host/test_instance_atmosphere_binding.py` exactly for fixture/import
shape; the surface binding has no debug readback, so these tests only prove
the call succeeds / raises for the right reasons.
"""
import pytest

pytest.importorskip("_dauntless_host")

import engine.renderer as r  # noqa: E402


def test_binding_is_present():
    """A stale build would silently drop the whole feature -- assert it loudly."""
    assert hasattr(r._h, "set_instance_surface")


def test_set_instance_surface_none_succeeds():
    iid = r.create_instance(0)
    try:
        r._h.set_instance_surface(iid, None)
    finally:
        r.destroy_instance(iid)


def test_set_instance_surface_eight_tuple_succeeds():
    iid = r.create_instance(0)
    try:
        r._h.set_instance_surface(
            iid, (1, (0.1, 0.2, 0.3), True, 0.15, 1.0, 1.0, 1.0, 123))
    finally:
        r.destroy_instance(iid)


def test_set_instance_surface_seven_tuple_raises():
    iid = r.create_instance(0)
    try:
        with pytest.raises(Exception):
            r._h.set_instance_surface(
                iid, (1, (0.1, 0.2, 0.3), True, 0.15, 1.0, 1.0, 1.0))
    finally:
        r.destroy_instance(iid)
