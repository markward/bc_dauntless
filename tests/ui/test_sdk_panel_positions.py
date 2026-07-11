from engine.appc.tg_ui.layout import Rect
from engine.ui.sdk_panel_positions import (
    build_position_script, PositionPusher, SDK_POSITIONED_PANELS,
)


def test_officer_menu_registered():
    assert SDK_POSITIONED_PANELS["officer-menu"] == "#crew-menu-host"


def test_script_sets_fixed_vwvh():
    js = build_position_script("officer-menu", Rect(0.0, 0.0, 0.143, 0.326))
    assert "#crew-menu-host" in js
    assert "position" in js and "fixed" in js
    assert "14.3vw" in js and "32.6vh" in js


def test_pusher_is_dirty_flagged():
    calls = []
    pusher = PositionPusher(lambda s: calls.append(s))
    r = Rect(0.0, 0.0, 0.143, 0.326)
    pusher.push({"officer-menu": r})
    pusher.push({"officer-menu": r})       # unchanged -> no second emit
    assert len(calls) == 1
    pusher.push({"officer-menu": Rect(0.0, 0.0, 0.2, 0.326)})  # changed -> emit
    assert len(calls) == 2
