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
    assert attack.envelop_dirs(7)[5] == attack.FACE_AXES[1]


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
