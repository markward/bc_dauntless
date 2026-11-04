"""Native render interpolation through the host bindings (phase 3c, host half).

A render instance with a SIM source (set_instance_sim_source) can be tracked
by the native interpolation buffer: `interp_track(iid, track, compose)`.
`interp_capture()` is the frame-end publish (cur = the live store pose),
`interp_roll()` starts a tick batch (prev = cur), `interp_reseat()` puts prev
on the live pose, and `interp_compose(alpha)` draws every compose-flagged
instance at lerp(prev, cur, alpha), times the source's scale, plus its view
offset. A LIVE instance (`interp_set_live`, the manually flown player) is drawn
from the store instead, and one handover blend (`interp_handover_*`) eases a
flip from the pose the compose last drew. `interp_sample(iid, alpha)` returns
that same drawn pose, set-local, before scale and offset.
"""
import math

import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.objects import ObjectClass  # noqa: E402

_ORIGIN = (0.0, 0.0, 0.0)


def _translation_mat(x, y, z):
    return [1.0, 0.0, 0.0, x,
            0.0, 1.0, 0.0, y,
            0.0, 0.0, 1.0, z,
            0.0, 0.0, 0.0, 1.0]


def _rotation(angle) -> TGMatrix3:
    """A rotation about a general axis, so a transposed or reflected
    composition cannot pass by accident."""
    axis = TGPoint3(1.0, 2.0, 3.0)
    axis.Scale(1.0 / math.sqrt(14.0))
    m = TGMatrix3()
    m.MakeRotation(angle, axis)
    return m


def _rot9(m: TGMatrix3):
    """Row-major nine doubles, the store's layout (column c = body axis c)."""
    cols = [m.GetCol(c) for c in range(3)]
    return tuple((cols[c].x, cols[c].y, cols[c].z)[r]
                 for r in range(3) for c in range(3))


def _drawn_x(iid):
    return _h.instance_translation(iid, drawn=True)[0]


def _drawn_body(iid, rel_point):
    """Body-frame image of an INSTANCE-RELATIVE point under the DRAWN pose."""
    body, _n = _h.world_to_body(iid, rel_point, (0.0, 0.0, 1.0), drawn=True)
    return body


def _expected_body(rot9, scale, p):
    """R^T p / s for a row-major rotation R."""
    return tuple(sum(rot9[r * 3 + c] * p[r] for r in range(3)) / scale
                 for c in range(3))


@pytest.fixture
def ship():
    """A model-0 instance whose sim source is an ObjectClass at the origin."""
    o = ObjectClass()
    o.SetTranslateXYZ(0.0, 0.0, 0.0)
    iid = _h.create_instance(0)
    _h.set_instance_sim_source(iid, *o._xform, 1.0, _ORIGIN)
    try:
        yield o, iid
    finally:
        _h.interp_handover_cancel()
        _h.destroy_instance(iid)


def test_bindings_present():
    for name in ("interp_track", "interp_roll", "interp_reseat",
                 "interp_capture", "interp_snap", "interp_reset_all",
                 "interp_set_live", "interp_handover_begin",
                 "interp_handover_advance", "interp_handover_cancel",
                 "interp_handover_active", "interp_sample", "interp_compose"):
        assert hasattr(_h, name), name


def test_compose_draws_the_lerp_with_scale_and_view_offset():
    rot = _rotation(0.7)
    o = ObjectClass()
    o.SetMatrixRotation(rot)
    o.SetTranslateXYZ(0.0, 0.0, 0.0)
    iid = _h.create_instance(0)
    try:
        _h.set_instance_sim_source(iid, *o._xform, 2.0, (10.0, 0.0, 0.0))
        _h.interp_track(iid, True, True)
        _h.interp_roll()
        o.SetTranslateXYZ(6.0, 0.0, 0.0)
        _h.interp_capture()
        _h.interp_compose(0.25)
        t = _h.instance_translation(iid, drawn=True)
        assert t == pytest.approx((11.5, 0.0, 0.0), abs=1e-9)
        # Drawn linear == 2 * rotation: its inverse maps p to R^T p / 2.
        p = (1.0, 2.0, 3.0)
        assert _drawn_body(iid, p) == pytest.approx(
            _expected_body(_rot9(rot), 2.0, p), abs=1e-6)
    finally:
        _h.destroy_instance(iid)


def test_capture_without_roll_moves_only_cur(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    # A per-frame writer (collision bounce, dash step) moves the ship in a
    # frame that runs no tick: capture again without a roll.
    o.SetTranslateXYZ(9.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(4.5, abs=1e-12)
    _h.interp_compose(1.0)
    assert _drawn_x(iid) == pytest.approx(9.0, abs=1e-12)


def test_reseat_puts_prev_one_tick_behind(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    o.SetTranslateXYZ(3.0, 0.0, 0.0)
    _h.interp_capture()
    # Multi-tick frame: before the last tick prev is re-seated on the live pose.
    o.SetTranslateXYZ(5.0, 0.0, 0.0)
    _h.interp_reseat()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(5.5, abs=1e-12)


def test_capture_skips_a_stale_source():
    iid = _h.create_instance(0)
    index, gen = _h.transform_alloc()
    try:
        _h.transform_set_position(index, gen, 2.0, 0.0, 0.0)
        _h.set_instance_sim_source(iid, index, gen, 1.0, _ORIGIN)
        _h.interp_track(iid, True, True)
        _h.interp_roll()
        _h.transform_set_position(index, gen, 4.0, 0.0, 0.0)
        _h.interp_capture()
        _h.transform_free(index, gen)
        _h.interp_capture()  # stale source: skipped, never raises
        _h.interp_compose(1.0)
        assert _drawn_x(iid) == pytest.approx(4.0, abs=1e-12)
        # A recycled slot is never read through the old handle.
        index2, gen2 = _h.transform_alloc()
        try:
            _h.transform_set_position(index2, gen2, 999.0, 0.0, 0.0)
            _h.interp_capture()
            _h.interp_reseat()
            _h.interp_compose(1.0)
            assert _drawn_x(iid) == pytest.approx(4.0, abs=1e-12)
        finally:
            _h.transform_free(index2, gen2)
    finally:
        _h.destroy_instance(iid)


def test_track_only_is_never_composed(ship):
    o, iid = ship
    _h.set_world_transform(iid, _translation_mat(5.0, 6.0, 7.0))
    o.SetTranslateXYZ(100.0, 0.0, 0.0)
    _h.interp_track(iid, True, False)
    _h.interp_compose(1.0)
    assert _h.instance_translation(iid, drawn=True) == (5.0, 6.0, 7.0)
    # Tracked all the same: the sample reads the snapshot.
    pos, _rot = _h.interp_sample(iid, 1.0)
    assert pos == pytest.approx((100.0, 0.0, 0.0), abs=1e-12)


def test_live_instance_draws_the_store_pose(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    o.SetTranslateXYZ(8.0, 0.0, 0.0)  # moved since the capture
    _h.interp_set_live(iid, True)
    _h.interp_compose(0.25)
    assert _drawn_x(iid) == pytest.approx(8.0, abs=1e-12)
    assert _h.interp_sample(iid, 0.25)[0][0] == pytest.approx(8.0, abs=1e-12)
    _h.interp_set_live(iid, False)
    _h.interp_compose(0.25)
    assert _drawn_x(iid) == pytest.approx(1.5, abs=1e-12)


def test_untrack_clears_the_live_flag(ship):
    """A re-tracked instance starts interpolated, as a new one does."""
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_set_live(iid, True)
    _h.interp_track(iid, False, False)
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_compose(0.25)
    assert _drawn_x(iid) == pytest.approx(1.5, abs=1e-12)

def test_handover_blends_from_the_last_drawn_pose(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_set_live(iid, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(6.0, abs=1e-12)  # live
    # live -> interpolated: the lerp (3.0) is a tick behind what was on screen.
    _h.interp_set_live(iid, False)
    _h.interp_handover_begin(iid)
    assert _h.interp_handover_active() is True
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(6.0, abs=1e-12)  # continuous
    _h.interp_handover_advance(0.18)  # half the window: smoothstep 0.5
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(4.5, abs=1e-12)
    _h.interp_handover_advance(0.18)
    assert _h.interp_handover_active() is False
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(3.0, abs=1e-12)  # the lerp


def test_handover_begin_without_a_drawn_pose_is_a_no_op(ship):
    _o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_handover_begin(iid)  # never composed: nothing to freeze
    assert _h.interp_handover_active() is False


def test_handover_cancel_snaps_to_truth(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_set_live(iid, True)
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_compose(0.0)
    _h.interp_set_live(iid, False)
    _h.interp_handover_begin(iid)
    _h.interp_handover_advance(0.09)
    _h.interp_handover_cancel()
    assert _h.interp_handover_active() is False
    _h.interp_compose(0.0)
    assert _drawn_x(iid) == pytest.approx(0.0, abs=1e-12)  # the snapshot


def test_a_push_clears_compose(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_compose(1.0)
    _h.set_world_transform(iid, _translation_mat(5.0, 6.0, 7.0))
    o.SetTranslateXYZ(100.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_compose(1.0)
    assert _h.instance_translation(iid, drawn=True) == (5.0, 6.0, 7.0)


def test_binding_to_a_slot_clears_compose(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    _h.set_instance_transform_slot(iid, *o._xform, 1.0)
    _h.interp_compose(0.0)  # would draw prev (0.0) if still composed
    assert _drawn_x(iid) == pytest.approx(6.0, abs=1e-12)
    # ...and the store binding survives it.
    o.SetTranslateXYZ(7.0, 0.0, 0.0)
    _h._test_only_sync_instance_transforms()
    assert _drawn_x(iid) == pytest.approx(7.0, abs=1e-12)


def test_destroy_erases_the_snapshot():
    o = ObjectClass()
    o.SetTranslateXYZ(100.0, 0.0, 0.0)
    first = _h.create_instance(0)
    _h.set_instance_sim_source(first, *o._xform, 1.0, _ORIGIN)
    _h.interp_track(first, True, True)
    _h.interp_compose(1.0)
    _h.destroy_instance(first)
    assert _h.interp_sample(first, 1.0) is None  # stale iid
    second = _h.create_instance(0)
    try:
        assert second.index == first.index  # the recycled slot
        # No sim source: nothing to seed from, and nothing inherited.
        _h.set_world_transform(second, _translation_mat(5.0, 6.0, 7.0))
        _h.interp_track(second, True, True)
        assert _h.interp_sample(second, 1.0) is None
        _h.interp_compose(1.0)
        assert _h.instance_translation(second, drawn=True) == (5.0, 6.0, 7.0)
    finally:
        _h.destroy_instance(second)


def test_reset_all_reseeds_on_next_capture(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_capture()
    _h.interp_reset_all()
    o.SetTranslateXYZ(8.0, 0.0, 0.0)
    _h.interp_capture()
    # Re-seeded: prev = cur = 8, no smear from the pre-reset snapshot. The
    # tracked and compose flags stay.
    _h.interp_compose(0.5)
    assert _drawn_x(iid) == pytest.approx(8.0, abs=1e-12)


def test_snap_puts_both_snapshots_on_the_live_pose(ship):
    o, iid = ship
    _h.interp_track(iid, True, True)
    _h.interp_roll()
    o.SetTranslateXYZ(6.0, 0.0, 0.0)
    _h.interp_snap(iid)
    _h.interp_compose(0.0)
    assert _drawn_x(iid) == pytest.approx(6.0, abs=1e-12)


def test_sample_is_none_for_an_untracked_or_stale_iid(ship):
    _o, iid = ship
    assert _h.interp_sample(iid, 0.5) is None
    _h.interp_track(iid, True, True)
    assert _h.interp_sample(iid, 0.5) is not None
    _h.interp_track(iid, False, False)
    assert _h.interp_sample(iid, 0.5) is None


def test_sample_matches_compose_before_scale_and_offset():
    r0, r1 = _rotation(0.3), _rotation(0.9)
    o = ObjectClass()
    o.SetMatrixRotation(r0)
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    iid = _h.create_instance(0)
    offset = (10.0, -4.0, 2.5)
    try:
        _h.set_instance_sim_source(iid, *o._xform, 2.0, offset)
        _h.interp_track(iid, True, True)
        _h.interp_set_live(iid, True)
        _h.interp_roll()
        o.SetMatrixRotation(r1)
        o.SetTranslateXYZ(7.0, -1.0, 4.0)
        _h.interp_capture()
        _h.interp_compose(0.3)
        _h.interp_set_live(iid, False)
        _h.interp_handover_begin(iid)
        _h.interp_handover_advance(0.1)  # mid-window: blended pose
        for _ in range(2):
            pos, rot9 = _h.interp_sample(iid, 0.3)
            _h.interp_compose(0.3)
            t = _h.instance_translation(iid, drawn=True)
            assert t == pytest.approx(
                tuple(pos[i] + offset[i] for i in range(3)), abs=1e-12)
            p = (1.0, 2.0, 3.0)
            assert _drawn_body(iid, p) == pytest.approx(
                _expected_body(rot9, 2.0, p), abs=1e-5)
            _h.interp_handover_advance(1.0)  # then the plain lerp
    finally:
        _h.destroy_instance(iid)
