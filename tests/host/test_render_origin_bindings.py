"""The floating render origin, at the binding boundary.

Every render instance keeps its translation in DOUBLE; C++ subtracts the
render origin once per frame before narrowing to float (Space pass only). The
mesh queries take points RELATIVE TO THE INSTANCE'S TRANSLATION and invert
only rotation*scale, so a ship 1e6 GU from the system origin is queried with
the precision of one at the origin. `instance_translation(iid)` hands Python
the double translation to form those relative points.
"""
import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine.appc.objects import ObjectClass  # noqa: E402

FAR_X = 1e6 + 0.3   # NOT a float: float32 rounds it to 1e6 + 0.3125


def _row_major(scale, tx, ty, tz):
    return [scale, 0.0, 0.0, tx,
            0.0, scale, 0.0, ty,
            0.0, 0.0, scale, tz,
            0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def iid():
    i = _h.create_instance(0)
    yield i
    _h.destroy_instance(i)


def test_premise_far_x_is_not_a_float32():
    import struct
    assert struct.unpack("f", struct.pack("f", FAR_X))[0] != FAR_X


def test_set_world_transform_keeps_the_translation_in_double(iid):
    _h.set_world_transform(iid, _row_major(1.0, FAR_X, -3e5 + 0.1, 7.5))
    assert _h.instance_translation(iid) == (FAR_X, -3e5 + 0.1, 7.5)


def test_a_store_bound_instance_keeps_the_translation_in_double(iid):
    o = ObjectClass()
    o.SetTranslateXYZ(FAR_X, 0.0, 0.0)
    _h.set_instance_transform_slot(iid, *o._xform, 1.0)
    assert _h.instance_translation(iid) == (FAR_X, 0.0, 0.0)
    o.SetTranslateXYZ(0.0, FAR_X, 0.0)
    _h._test_only_sync_instance_transforms()
    assert _h.instance_translation(iid) == (0.0, FAR_X, 0.0)


def test_instance_translation_of_a_stale_id_is_none():
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.instance_translation(stale) is None


def test_world_to_body_is_instance_relative_and_precise_a_million_gu_out(iid):
    # Game scale (x0.01), 1e6 + 0.3 GU out. A hit 0.004 GU from the ship's
    # origin -- far below float's 1/16 GU there -- is formed relative in
    # double and lands at 0.4 model units.
    _h.set_world_transform(iid, _row_major(0.01, FAR_X, 0.0, 0.0))
    tx, ty, tz = _h.instance_translation(iid)
    hit = (FAR_X + 0.004, 0.0, 0.0)
    rel = (hit[0] - tx, hit[1] - ty, hit[2] - tz)
    body, normal = _h.world_to_body(iid, rel, (1.0, 0.0, 0.0))
    assert body == pytest.approx((0.4, 0.0, 0.0), abs=1e-4)
    assert normal == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)


def test_set_render_origin_does_not_move_a_mesh_query(iid):
    _h.set_world_transform(iid, _row_major(2.0, FAR_X, 0.0, 0.0))
    before = _h.world_to_body(iid, (2.0, 4.0, 6.0), (0.0, 0.0, 1.0))
    _h.set_render_origin(FAR_X - 50.0, 0.0, 0.0)
    try:
        after = _h.world_to_body(iid, (2.0, 4.0, 6.0), (0.0, 0.0, 1.0))
    finally:
        _h.set_render_origin(0.0, 0.0, 0.0)
    assert after == before
    assert before[0] == pytest.approx((1.0, 2.0, 3.0), abs=1e-6)
