"""Unit tests for the render transform snapshot buffer."""

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.transform_buffer import TransformBuffer


def _ident():
    m = TGMatrix3(); m.MakeIdentity(); return m


def test_new_iid_seeds_prev_equal_to_cur_no_smear():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(10.0, 0.0, 0.0), _ident())
    loc, _rot = buf.sample(7, 0.0)
    assert (loc.x, loc.y, loc.z) == (10.0, 0.0, 0.0)
    loc1, _ = buf.sample(7, 1.0)
    assert (loc1.x, loc1.y, loc1.z) == (10.0, 0.0, 0.0)  # prev == cur


def test_roll_then_set_current_interpolates_across_last_tick():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())  # frame 0 seed
    buf.roll()                                             # frame 1: cur -> prev
    buf.set_current(7, TGPoint3(4.0, 0.0, 0.0), _ident())  # new cur
    loc, _ = buf.sample(7, 0.0)
    assert loc.x == 0.0          # alpha 0 -> prev
    loc, _ = buf.sample(7, 0.5)
    assert loc.x == 2.0          # midpoint
    loc, _ = buf.sample(7, 1.0)
    assert loc.x == 4.0          # alpha 1 -> cur


def test_zero_tick_frame_keeps_state():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.roll()
    buf.set_current(7, TGPoint3(4.0, 0.0, 0.0), _ident())
    # A 0-tick frame: no roll, no set_current. Sampling still works and
    # alpha grows toward cur as the accumulator fills.
    loc, _ = buf.sample(7, 0.75)
    assert loc.x == 3.0


def test_reset_all_clears_stale_state():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.roll()
    buf.set_current(7, TGPoint3(999.0, 0.0, 0.0), _ident())
    buf.reset_all()
    # After a swap: re-seed; first sample renders at live, no smear.
    buf.set_current(7, TGPoint3(5.0, 0.0, 0.0), _ident())
    loc, _ = buf.sample(7, 0.0)
    assert loc.x == 5.0
    loc, _ = buf.sample(7, 1.0)
    assert loc.x == 5.0


def test_prune_drops_absent_iids():
    buf = TransformBuffer()
    buf.set_current(7, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.set_current(8, TGPoint3(0.0, 0.0, 0.0), _ident())
    buf.prune({7})
    assert buf.has(7)
    assert not buf.has(8)


def test_sample_unknown_iid_returns_none():
    buf = TransformBuffer()
    assert buf.sample(99, 0.5) is None
