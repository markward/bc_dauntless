from engine.appc.tg_ui.layout import Rect
from engine.ui.sdk_panel_positions import (
    build_position_script, PositionPusher, SDK_POSITIONED_PANELS,
)


def test_crew_menu_is_never_sdk_positioned():
    """#crew-menu-host is a Dauntless-designed flex child of
    #tactical-target-stack (crew_menus.css) — it collapses to zero height
    when nothing is open and otherwise sizes itself via CSS. SDK-positioning
    it (former "officer-menu" entry) pushed position:fixed + a headless-
    resolved rect (left:0vw top:0vh, height often 0vh) onto it every frame,
    yanking it out of its flex flow into the screen's top-left corner —
    under E1M1's cutscene letterbox — so the XO's raised menu was invisible/
    unreachable and the tutorial halted. The crew menu must never appear as
    a target in SDK_POSITIONED_PANELS; only SDK-invented ad-hoc panels
    (ShowInfoBox/TextBanner/EpisodeTitleAction) with no competing CEF layout
    belong here.
    """
    assert "#crew-menu-host" not in SDK_POSITIONED_PANELS.values()


def test_script_sets_fixed_vwvh(monkeypatch):
    monkeypatch.setitem(SDK_POSITIONED_PANELS, "test-panel", "#test-panel-host")
    js = build_position_script("test-panel", Rect(0.0, 0.0, 0.143, 0.326))
    assert "#test-panel-host" in js
    assert "position" in js and "fixed" in js
    assert "14.3vw" in js and "32.6vh" in js


def test_pusher_is_dirty_flagged(monkeypatch):
    monkeypatch.setitem(SDK_POSITIONED_PANELS, "test-panel", "#test-panel-host")
    calls = []
    pusher = PositionPusher(lambda s: calls.append(s))
    r = Rect(0.0, 0.0, 0.143, 0.326)
    pusher.push({"test-panel": r})
    pusher.push({"test-panel": r})       # unchanged -> no second emit
    assert len(calls) == 1
    pusher.push({"test-panel": Rect(0.0, 0.0, 0.2, 0.326)})  # changed -> emit
    assert len(calls) == 2
