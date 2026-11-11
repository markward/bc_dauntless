import math

import pytest

from engine.wings import attack
from engine.wings.assess import ShipView


def _angle(a, b):
    d = sum(x * y for x, y in zip(a, b))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def test_weakest_face_picks_lowest_and_ties_low_index():
    assert attack.weakest_face((1, 1, 0.5, 0.5, 1, 1)) == (2, 0.5)
    assert attack.weakest_face(()) is None


def test_focus_dirs_single_is_axis():
    (d,) = attack.focus_dirs(4, 1)
    assert d == pytest.approx((-1.0, 0.0, 0.0))


def test_focus_dirs_spread_within_arc():
    dirs = attack.focus_dirs(4, 3)
    angles = []
    for d in dirs:
        assert math.sqrt(sum(c * c for c in d)) == pytest.approx(1.0)
        assert d[2] == pytest.approx(0.0)
        angles.append(_angle(d, (-1, 0, 0)))
    assert max(angles) <= 25.0 + 1e-6
    assert max(angles) == pytest.approx(25.0)


def test_focus_dirs_top_spreads_about_x():
    dirs = attack.focus_dirs(2, 2)
    for d in dirs:
        assert d[0] == pytest.approx(0.0)
        assert _angle(d, (0, 0, 1)) == pytest.approx(25.0)


def test_envelop_dirs_order_and_cycle():
    assert attack.envelop_dirs(3) == (
        attack.FACE_AXES[1], attack.FACE_AXES[4], attack.FACE_AXES[5])
    assert len(attack.envelop_dirs(7)) == 7
    # The second wrap is rear again, turned 25 degrees (review M2).
    assert _angle(attack.envelop_dirs(7)[5], attack.FACE_AXES[1]) == (
        pytest.approx(25.0))


def _distinct(points, tol=1e-6):
    return all(sum((a - b) ** 2 for a, b in zip(p, q)) > tol
               for i, p in enumerate(points) for q in points[i + 1:])


def test_seven_slots_seven_distinct_points():
    """Review M2: disable with more holders than directions never stacks
    two holders on one point."""
    cols = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    dirs = attack.envelop_dirs(7)
    assert _distinct([attack.slot_point((0, 0, 0), cols, d, 120.0)
                      for d in dirs])
    for d in dirs:
        assert math.sqrt(sum(c * c for c in d)) == pytest.approx(1.0)


def test_spread_dirs_cycles_and_turns_each_wrap():
    base = (attack.FACE_AXES[1], attack.FACE_AXES[4])
    out = attack.spread_dirs(base, 5)
    assert out[:2] == base
    assert _distinct(out)
    assert _angle(out[2], base[0]) == pytest.approx(25.0)
    assert _angle(out[4], base[0]) == pytest.approx(50.0)
    top = attack.spread_dirs((attack.FACE_AXES[2],), 2)
    assert top[1][0] == pytest.approx(0.0)       # about x, as focus_dirs
    assert _distinct(attack.envelop_dirs(15))


def test_slot_point_rotates_body_dir():
    cols = ((0, 1, 0), (-1, 0, 0), (0, 0, 1))
    p = attack.slot_point((10, 0, 0), cols, (-1, 0, 0), 120.0)
    assert p == pytest.approx((10, -120, 0))


def V(name, x):
    return ShipView(name, (x, 0, 0), 1.0, 1.0, 1.0)


def test_assign_slots_greedy_nearest():
    cands = [V("a", 0), V("b", 10)]
    points = [(12, 0, 0), (-1, 0, 0)]
    assert attack.assign_slots(cands, points) == {"b": 0, "a": 1}
    three = [V("a", 0), V("b", 10), V("c", 20)]
    assert len(attack.assign_slots(three, points)) == 2


def test_assign_slots_incumbents_keep_their_slot():
    """Final review I2: a previous holder that is still a candidate keeps
    its slot index even when another candidate is now nearer to it."""
    cands = [V("a", 0), V("b", 10)]
    points = [(12, 0, 0), (-1, 0, 0)]
    assert attack.assign_slots(cands, points, {"a": 0, "b": 1}) == {
        "a": 0, "b": 1}


def test_assign_slots_vacated_slot_filled_nearest():
    cands = [V("a", 0), V("c", 100), V("d", 13)]
    points = [(12, 0, 0), (-1, 0, 0)]
    # "b" held slot 0 and is gone: the nearest remaining candidate takes it.
    got = attack.assign_slots(cands, points, {"a": 1, "b": 0})
    assert got == {"a": 1, "d": 0}


def test_assign_slots_prev_index_out_of_range_is_refilled():
    cands = [V("a", 0), V("b", 10)]
    points = [(12, 0, 0)]
    assert attack.assign_slots(cands, points, {"a": 3}) == {"b": 0}


def test_assign_slots_two_prev_on_one_index_keep_one():
    cands = [V("a", 0), V("b", 10)]
    points = [(12, 0, 0), (-1, 0, 0)]
    got = attack.assign_slots(cands, points, {"a": 0, "b": 0})
    assert sorted(got.values()) == [0, 1] and got["a"] == 0


# ── slot standoff from each holder's beam range (ruling 2026-11-09) ────────

def test_beam_range_is_the_smallest_positive():
    assert attack.beam_range([60.0, 40.0, 30.0]) == 30.0
    assert attack.beam_range([0.0, 50.0]) == 50.0
    assert attack.beam_range([]) is None
    assert attack.beam_range([0.0]) is None


def test_holder_standoff_is_four_fifths_of_range_clamped():
    assert attack.holder_standoff(40.0, 25.0, 80.0) == pytest.approx(32.0)
    assert attack.holder_standoff(60.0, 25.0, 80.0) == pytest.approx(48.0)
    assert attack.holder_standoff(30.0, 25.0, 80.0) == pytest.approx(25.0)
    assert attack.holder_standoff(10.0, 25.0, 80.0) == 25.0
    assert attack.holder_standoff(200.0, 25.0, 80.0) == 80.0
    assert attack.holder_standoff(None, 25.0, 80.0) == 80.0   # no beams
    assert attack.holder_standoff(60.0, 90.0, 80.0) == 80.0   # the cap wins
