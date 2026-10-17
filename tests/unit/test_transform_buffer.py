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
    # _prev must be cleaned up too, not just _cur (has() only reads _cur).
    assert buf.sample(8, 0.5) is None


def test_sample_unknown_iid_returns_none():
    buf = TransformBuffer()
    assert buf.sample(99, 0.5) is None


# --- multi-tick frames (motion-trace finding 2026-10-17) ---------------------
# A render frame slower than one tick runs 2+ ticks. prev must be the pose
# before the LAST tick, so lerp(prev, cur, alpha) spans exactly one tick like
# alpha does. Rolled once before the batch, prev sat 2 ticks back: the drawn
# ship lagged on every 2-tick frame and leapt on the next (E1M1 undock at
# ~20 ms frames: steps of 0.02 then 0.10 GU against an even 0.05).

from engine.core.transform_buffer import advance_ticks


class _Ship:
    def __init__(self):
        self.x = 0.0

    def poses(self):
        return [(7, TGPoint3(self.x, 0.0, 0.0), _ident())]


def _frame(buf, ship, n):
    def tick():
        ship.x += 1.0
    advance_ticks(buf, n, tick, ship.poses)
    if n:
        buf.set_current(7, TGPoint3(ship.x, 0.0, 0.0), _ident())


def test_two_tick_frame_interpolates_across_the_last_tick_only():
    buf, ship = TransformBuffer(), _Ship()
    _frame(buf, ship, 1)                  # seed: x = 1
    _frame(buf, ship, 2)                  # x 1 -> 3
    assert buf.sample(7, 0.0)[0].x == 2.0     # pose before the last tick
    assert buf.sample(7, 0.5)[0].x == 2.5


def test_one_tick_frame_is_unchanged():
    buf, ship = TransformBuffer(), _Ship()
    _frame(buf, ship, 1)
    _frame(buf, ship, 1)                  # x 1 -> 2
    assert buf.sample(7, 0.0)[0].x == 1.0
    assert buf.sample(7, 1.0)[0].x == 2.0


def test_zero_tick_frame_runs_nothing_and_keeps_the_snapshots():
    buf, ship = TransformBuffer(), _Ship()
    _frame(buf, ship, 1)
    _frame(buf, ship, 1)
    _frame(buf, ship, 0)
    assert ship.x == 2.0
    assert buf.sample(7, 0.5)[0].x == 1.5


def test_drawn_motion_is_even_across_mixed_tick_frames():
    """The undock pattern: 2,1,1,1 ticks per frame at a steady 20 ms. Sampled
    at the accumulator's alpha, the drawn x advances by a constant 1.2 ticks
    per frame."""
    from engine.core.timestep import step_accumulator
    tick_dt, frame_dt = 1.0 / 60.0, 0.020
    buf, ship = TransformBuffer(), _Ship()
    acc, drawn = 0.0, []
    for _ in range(40):
        acc, n = step_accumulator(acc, frame_dt, tick_dt, 0.25)
        _frame(buf, ship, n)
        if ship.x:
            drawn.append(buf.sample(7, acc / tick_dt)[0].x)
    steps = [b - a for a, b in zip(drawn[5:], drawn[6:])]
    assert max(steps) - min(steps) < 1e-9, steps


def test_untracked_live_poses_are_ignored():
    """A pose for an iid the buffer is not tracking (the manually-flown
    player) must not start tracking it."""
    buf = TransformBuffer()
    advance_ticks(buf, 2, lambda: None,
                  lambda: [(9, TGPoint3(1.0, 0.0, 0.0), _ident())])
    assert not buf.has(9)
