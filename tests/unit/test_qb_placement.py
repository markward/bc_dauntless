import pytest

from engine.quickbattle import placement as pl

COLS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))   # identity: stbd, fore, dorsal
ORIGIN = (10.0, 20.0, 30.0)


@pytest.mark.parametrize("direction,axis", [
    ("fore", (0, 1, 0)), ("aft", (0, -1, 0)), ("starboard", (1, 0, 0)),
    ("port", (-1, 0, 0)), ("dorsal", (0, 0, 1)), ("ventral", (0, 0, -1))])
def test_axis_for_each_direction(direction, axis):
    assert pl.axis_for(direction, COLS) == pytest.approx(axis)


def test_axis_follows_a_rotated_player():
    rot = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))   # yawed 90 degrees
    assert pl.axis_for("fore", rot) == pytest.approx((-1, 0, 0))
    assert pl.lateral_for("fore", rot) == pytest.approx((0, 1, 0))


def test_lateral_axis_choice():
    assert pl.lateral_for("fore", COLS) == pytest.approx((1, 0, 0))
    assert pl.lateral_for("dorsal", COLS) == pytest.approx((1, 0, 0))
    assert pl.lateral_for("port", COLS) == pytest.approx((0, 1, 0))


def test_slot_offsets_alternate_and_pack_by_radii():
    m = pl.MARGIN_GU
    assert pl.slot_offsets([1.0]) == [0.0]
    off = pl.slot_offsets([1.0, 1.0, 1.0])
    assert off == pytest.approx([0.0, 2.0 + m, -(2.0 + m)])
    big = pl.slot_offsets([1.0, 5.0])        # a station next to a shuttle
    assert big[1] == pytest.approx(1.0 + 5.0 + m)


def test_single_ship_sits_on_the_anchor():
    [p] = pl.group_positions(ORIGIN, COLS, "fore", 200.0, [1.0])
    assert p == pytest.approx((10.0, 220.0, 30.0))


def test_rows_of_five_then_further_away():
    pos = pl.group_positions(ORIGIN, COLS, "fore", 200.0, [1.0] * 7)
    assert all(p[1] == pytest.approx(220.0) for p in pos[:5])
    gap = 1.0 + 1.0 + pl.MARGIN_GU
    assert all(p[1] == pytest.approx(220.0 + gap) for p in pos[5:])
    assert pos[5][0] == pytest.approx(10.0)          # second row restarts at the centre


def test_deterministic():
    a = pl.group_positions(ORIGIN, COLS, "aft", 457.0, [1.0, 2.0, 3.0])
    b = pl.group_positions(ORIGIN, COLS, "aft", 457.0, [1.0, 2.0, 3.0])
    assert a == b


def test_escorts_beside_player_starboard_first():
    m = pl.MARGIN_GU
    pos = pl.escort_positions(ORIGIN, COLS, 2.0, [1.0, 1.0, 1.0])
    assert pos[0] == pytest.approx((10.0 + 2.0 + 1.0 + m, 20.0, 30.0))
    assert pos[1] == pytest.approx((10.0 - (2.0 + 1.0 + m), 20.0, 30.0))
    assert pos[2][0] > pos[0][0]


def test_only_enemies_face_the_player():
    assert pl.faces_player("enemy")
    assert not pl.faces_player("friendly") and not pl.faces_player("neutral")
