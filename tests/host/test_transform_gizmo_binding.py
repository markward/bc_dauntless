"""set_transform_gizmo / clear_transform_gizmo exist and accept the payload.
Headless: we only assert the bindings are present and callable (no GL)."""
import pytest

_h = pytest.importorskip("_dauntless_host")


def test_transform_gizmo_bindings_present():
    assert hasattr(_h, "set_transform_gizmo")
    assert hasattr(_h, "clear_transform_gizmo")


def test_set_transform_gizmo_accepts_payload():
    # origin, three axes, length, highlight, handle_kind — must not raise.
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1, 0)
    _h.clear_transform_gizmo()


def test_set_transform_gizmo_accepts_handle_kind():
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1, 1)   # trailing handle_kind = cube
    _h.clear_transform_gizmo()


def test_set_transform_gizmo_accepts_ring_handle_kind():
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1, 2)   # handle_kind 2 = rings
    _h.clear_transform_gizmo()
