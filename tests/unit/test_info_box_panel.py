"""InfoBoxPanel observation + serialization."""
import json

import pytest

import App
from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
from engine.appc.tg_ui.widgets import TGParagraph
from engine.appc.characters import STButton
from engine.ui.info_box_panel import InfoBoxPanel


@pytest.fixture(autouse=True)
def _clean_tcw():
    tcw = TacticalControlWindow.GetInstance()
    tcw._children.clear()
    _STStylizedWindow._counter = 0
    yield
    tcw._children.clear()


def _build_box(title="Tactical View Help", visible=True):
    box = _STStylizedWindow(title)
    pane = App.TGPane_Create(100.0, 100.0)
    body = TGParagraph("Use these keys:")
    body.AppendChar(App.WC_RETURN)
    glyph = TGParagraph("W")
    glyph.SetColor(App.NiColorA_WHITE)
    body.AddChild(glyph)
    body.AppendStringW(" accelerate")
    pane.AddChild(body)
    pane.AddChild(STButton("Close"))
    box.AddChild(pane)
    if not visible:
        box.SetNotVisible()
    TacticalControlWindow.GetInstance().AddChild(box)
    return box


def _entries(panel):
    js = panel.render_payload()
    assert js.startswith("setInfoBoxes(")
    return json.loads(js[len("setInfoBoxes("):-2])["entries"]


def test_visible_box_is_serialized():
    box = _build_box()
    entries = _entries(InfoBoxPanel())
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == box._id
    assert e["title"] == "Tactical View Help"
    assert e["button"]["label"] == "Close"
    assert e["button"]["id"] == box._id


def test_body_segments_and_key_chip():
    _build_box()
    body = _entries(InfoBoxPanel())[0]["body"]
    assert {"kind": "text", "text": "Use these keys:"} in body
    assert {"kind": "text", "text": "\n"} in body
    key = [s for s in body if s["kind"] == "key"]
    assert len(key) == 1
    assert key[0]["text"] == "W"
    assert key[0]["color"] == [1.0, 1.0, 1.0, 1.0]
    assert {"kind": "text", "text": " accelerate"} in body


def test_hidden_box_is_not_serialized():
    _build_box(visible=False)
    assert _entries(InfoBoxPanel()) == []


def test_dedup_returns_none_when_unchanged():
    _build_box()
    panel = InfoBoxPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None


def test_invalidate_forces_reemit():
    _build_box()
    panel = InfoBoxPanel()
    panel.render_payload()
    panel.invalidate()
    assert panel.render_payload() is not None


# ── Undefined App colour globals must not kill the frame ─────────────────────
# E1M1's tactical-view help box (E1M1.py:3343) passes
# App.g_kMainMenuButton2HighlightedColor to TGParagraph_CreateW.  That name is
# undefined, so it is a truthy _NamedStub -- and a stub answers hasattr() for
# EVERY name, so _color_to_list's hasattr gate let four stubs through into
# json.dumps and raised TypeError mid-frame, a fatal error in-game.
#
# 40 of the 51 g_k*Color globals the SDK references are undefined this way, so
# this is a class of crash, not one constant.  They are INSTANCES, not scalars,
# which is why the q13 constant sweep neither caused nor could have fixed it.
#
# Note float(stub) returns 0.0 rather than raising, so a try/float guard would
# silently paint every such colour black.  The component TYPE is the only
# reliable discriminator.

def test_undefined_app_colour_global_serialises_as_no_colour():
    import App
    from engine.ui.info_box_panel import _color_to_list

    stub = App.g_kMainMenuButton2HighlightedColor  # a real, still-undefined name
    assert all(hasattr(stub, k) for k in "rgba"), (
        "precondition: the stub answers hasattr for every component -- this is "
        "why the old hasattr gate could not reject it")
    assert _color_to_list(stub) is None


def test_info_box_payload_with_a_stub_colour_is_json_serialisable():
    import json
    import App
    from engine.ui.info_box_panel import _color_to_list

    payload = {"entries": [{"color": _color_to_list(
        App.g_kMainMenuButton2HighlightedColor)}]}
    json.dumps(payload)  # must not raise


def test_a_real_colour_still_serialises():
    import json
    from App import TGColorA
    from engine.ui.info_box_panel import _color_to_list

    rgba = _color_to_list(TGColorA(0.25, 0.5, 0.75, 1.0))
    assert rgba == [0.25, 0.5, 0.75, 1.0]
    json.dumps(rgba)


# ── Modal-blocker protocol: ESC + click routing ─────────────────────────────
# Live bug (E1M1 tactical help box): Close did nothing and ESC raised the
# pause menu UNDER the box. Two host-loop seams were missing — the info box
# was not in the ESC ladder (_modal_blockers), and the centred #sdk-infobox
# had no click-forwarding bbox, so the Close click fell through to the 3D
# view. The panel now satisfies is_open()/handle_key_esc() and learns its
# on-screen rect from JS ("bounds:x,y,w,h") so the host loop can gate click
# forwarding on it.

def _build_sdk_box(close_button):
    """A box built by the REAL MissionLib helper, so the Close button's
    ET_INPUT_CLOSE_MENU event and MissionLib.CloseInfoBox handler are the
    genuine SDK wiring, not a test double."""
    import MissionLib
    player = App.TGEventHandlerObject()
    box = MissionLib.SetupInfoBox("StylizedWindow", "body", 300, 200,
                                  None, None, App.ET_CHARACTER_MENU, player,
                                  close_button)
    TacticalControlWindow.GetInstance().AddChild(box, 0, 0)
    box.SetVisible()
    return box


def test_is_open_only_when_a_closeable_box_is_visible():
    panel = InfoBoxPanel()
    assert panel.is_open() is False
    _build_sdk_box(close_button=0)          # E1M1's Picard box: no Close
    panel.render_payload()
    assert panel.is_open() is False, "a box with no Close button cannot own ESC"
    box = _build_sdk_box(close_button=1)
    panel.render_payload()
    assert panel.is_open() is True
    box.SetNotVisible()
    panel.render_payload()
    assert panel.is_open() is False


def test_handle_key_esc_closes_the_closeable_box_through_its_close_button():
    panel = InfoBoxPanel()
    inert = _build_sdk_box(close_button=0)
    box = _build_sdk_box(close_button=1)
    panel.render_payload()
    panel.handle_key_esc()
    assert box.IsVisible() == 0
    assert inert.IsVisible() == 1, "ESC must not touch a box that has no Close"


def test_esc_through_the_modal_dispatcher_closes_the_box_not_the_pause_menu():
    from engine.host_loop import _dispatch_modal_esc, _PauseMenuController

    class _Keys:
        KEY_ESCAPE = 256

    class _Host:
        keys = _Keys()
        def key_pressed(self, key):
            return key == _Keys.KEY_ESCAPE

    class _NoCrewMenu:
        def has_open_menu(self):
            return False

    panel = InfoBoxPanel()
    box = _build_sdk_box(close_button=1)
    panel.render_payload()
    pause = _PauseMenuController()
    _dispatch_modal_esc([panel], _NoCrewMenu(), pause, _Host())
    assert box.IsVisible() == 0
    assert pause.is_open is False


def test_bounds_event_records_the_click_rect():
    panel = InfoBoxPanel()
    _build_sdk_box(close_button=1)
    panel.render_payload()
    assert panel.dispatch_event("bounds:400,250,480,320") is True
    assert panel.cursor_in_bounds(400, 250) is True
    assert panel.cursor_in_bounds(879, 569) is True
    assert panel.cursor_in_bounds(880, 569) is False, "half-open, like the sibling bboxes"
    assert panel.cursor_in_bounds(10, 10) is False


def test_bounds_are_ignored_while_no_box_is_open():
    panel = InfoBoxPanel()
    panel.dispatch_event("bounds:0,0,1280,720")
    assert panel.cursor_in_bounds(100, 100) is False, (
        "a stale rect must never swallow phaser fire after the box closes")


def test_malformed_bounds_are_dropped():
    panel = InfoBoxPanel()
    assert panel.dispatch_event("bounds:garbage") is True
    assert panel.cursor_in_bounds(0, 0) is False
