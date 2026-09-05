"""A render instance bound to a store slot follows its object without the
transform crossing into Python.

`set_instance_transform_slot(iid, index, generation, scale)` binds a render
instance to a TransformStore slot; the renderer composes the instance's world
matrix from the store (in C++, downconverted to float at the GL boundary)
instead of receiving a 16-float matrix from Python every frame. `index < 0`
unbinds and restores the explicit-matrix path.
"""
import math

import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.objects import ObjectClass  # noqa: E402
from engine.host_loop import _world_matrix_from  # noqa: E402


def test_binding_is_present():
    """A stale build would silently drop the whole feature — assert it loudly."""
    assert hasattr(_h, "set_instance_transform_slot")


def test_unbind_is_accepted():
    """index = -1 unbinds; must not raise even when nothing was bound."""
    iid = _h.create_instance(0)
    try:
        _h.set_instance_transform_slot(iid, -1, 0, 1.0)
    finally:
        _h.destroy_instance(iid)


def test_binding_a_live_handle_does_not_raise():
    o = ObjectClass()
    o.SetTranslateXYZ(3.0, 4.0, 5.0)
    index, generation = o._xform
    iid = _h.create_instance(0)
    try:
        _h.set_instance_transform_slot(iid, index, generation, 1.0)
    finally:
        _h.destroy_instance(iid)


def _asymmetric_rotation() -> TGMatrix3:
    """A rotation about a general axis, so a transposed (or reflected)
    composition cannot accidentally pass."""
    axis = TGPoint3(1.0, 2.0, 3.0)
    axis.Scale(1.0 / math.sqrt(14.0))
    m = TGMatrix3()
    m.MakeRotation(0.7, axis)
    return m


def _probe_body(iid, point):
    body, _normal = _h.world_to_body(iid, point, (0.0, 0.0, 1.0))
    return body


def _apply_inverse(mat4, point):
    """Body-frame image of `point` under the row-major TRS `mat4`.

    The rotation block is R*s with R orthonormal, so the inverse of the block
    is its transpose divided by s^2; translation is the fourth column.
    """
    t = (mat4[3], mat4[7], mat4[11])
    d = [point[i] - t[i] for i in range(3)]
    s2 = mat4[0] ** 2 + mat4[4] ** 2 + mat4[8] ** 2  # |column 0|^2 = s^2
    return tuple(
        sum(mat4[r * 4 + c] * d[r] for r in range(3)) / s2 for c in range(3)
    )


def test_composed_matrix_matches_world_matrix_from():
    """The C++ composition must reproduce host_loop._world_matrix_from.

    Probed through world_to_body, which reads the instance's composed world
    matrix. Four independent probe points pin all twelve meaningful elements:
    the origin fixes the translation column, the three axis points fix the
    rotation-times-scale block. A transpose or an X-column flip fails this.
    """
    scale = 2.5
    o = ObjectClass()
    o.SetTranslateXYZ(3.0, -4.0, 5.0)
    o.SetMatrixRotation(_asymmetric_rotation())
    iid = _h.create_instance(0)
    try:
        _h.set_instance_transform_slot(iid, *o._xform, scale)
        _h._debug_sync_instance_transforms()
        expected = _world_matrix_from(
            o.GetWorldLocation(), o.GetWorldRotation(), scale)
        for probe in ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0),
                      (0.0, 100.0, 0.0), (0.0, 0.0, 100.0)):
            got = _probe_body(iid, probe)
            want = _apply_inverse(expected, probe)
            assert got == pytest.approx(want, abs=1e-3), probe
    finally:
        _h.destroy_instance(iid)


def test_bound_instance_follows_the_object_without_a_python_push():
    """Moving the object updates the instance's world matrix with no
    set_world_transform call — that is the whole point of the binding."""
    o = ObjectClass()
    o.SetTranslateXYZ(0.0, 0.0, 0.0)
    iid = _h.create_instance(0)
    try:
        _h.set_instance_transform_slot(iid, *o._xform, 1.0)
        o.SetTranslateXYZ(50.0, 0.0, 0.0)
        # The per-frame sweep frame() runs; no transform crossed into Python.
        _h._debug_sync_instance_transforms()
        # World point (50,0,0) is now the object's origin.
        assert _probe_body(iid, (50.0, 0.0, 0.0)) == pytest.approx(
            (0.0, 0.0, 0.0), abs=1e-4)
    finally:
        _h.destroy_instance(iid)


def test_unbind_restores_the_explicit_matrix_path():
    """After unbinding, an explicitly pushed matrix stays put."""
    o = ObjectClass()
    o.SetTranslateXYZ(10.0, 0.0, 0.0)
    iid = _h.create_instance(0)
    try:
        _h.set_instance_transform_slot(iid, *o._xform, 1.0)
        _h.set_instance_transform_slot(iid, -1, 0, 1.0)
        _h.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        o.SetTranslateXYZ(999.0, 0.0, 0.0)   # must NOT move the instance
        _h._debug_sync_instance_transforms()
        assert _probe_body(iid, (7.0, 0.0, 0.0)) == pytest.approx(
            (7.0, 0.0, 0.0), abs=1e-4)
    finally:
        _h.destroy_instance(iid)
