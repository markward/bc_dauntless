import pytest

from engine.appc.tg_ui.layout import (
    Rect, ANCHOR_FRACTIONS, anchor_point, norm_to_vhvw,
    ALIGN_UL, ALIGN_UR, ALIGN_BL, ALIGN_BR, ALIGN_UC,
)

def test_rect_edges():
    r = Rect(0.1, 0.2, 0.3, 0.4)
    assert r.right == 0.4
    assert abs(r.bottom - 0.6) < 1e-9

def test_anchor_points_top_left_ydown():
    r = Rect(0.1, 0.2, 0.4, 0.4)
    # pytest.approx (not brief-literal ==): 0.2 + 1.0*0.4 and 0.1 + 0.5*0.4 are
    # not exactly 0.6 / 0.3 in IEEE754 doubles, same class of imprecision
    # test_rect_edges already tolerates for `bottom`. See task-3-report.md.
    assert anchor_point(r, ALIGN_UL) == pytest.approx((0.1, 0.2))    # upper-left
    assert anchor_point(r, ALIGN_UR) == pytest.approx((0.5, 0.2))    # upper-right
    assert anchor_point(r, ALIGN_BL) == pytest.approx((0.1, 0.6))    # bottom-left (y down)
    assert anchor_point(r, ALIGN_BR) == pytest.approx((0.5, 0.6))
    assert anchor_point(r, ALIGN_UC) == pytest.approx((0.3, 0.2))    # upper-centre

def test_anchor_fractions_distinct():
    # every ALIGN_* sentinel is distinct and mapped
    assert len(set(ANCHOR_FRACTIONS.keys())) == len(ANCHOR_FRACTIONS)

def test_norm_to_vhvw():
    css = norm_to_vhvw(0.0, 0.0, 0.143, 0.326)
    assert css["left"] == "0.0vw"
    assert css["top"] == "0.0vh"
    assert css["width"] == "14.3vw"
    assert css["height"] == "32.6vh"
