# tests/integration/test_info_box_close_round_trip.py
"""CEF close click → real SDK close event → box hidden + handler ran."""
import sys
import types

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


def _close_handler_module():
    mod = types.ModuleType("_tmp_infobox_close")
    mod.closed = []

    def CloseInfoBox(box, event):
        box.SetNotVisible()
        mod.closed.append(box)

    mod.CloseInfoBox = CloseInfoBox
    sys.modules[mod.__name__] = mod
    return mod


def _build_box():
    # Mirrors MissionLib.SetupInfoBoxFromParagraph structure.
    box = _STStylizedWindow("Tactical View Help")
    pane = App.TGPane_Create(100.0, 100.0)
    pane.AddChild(TGParagraph("body"))
    close_event = App.TGEvent_Create()
    close_event.SetEventType(App.ET_INPUT_CLOSE_MENU)
    close_event.SetDestination(box)
    pane.AddChild(STButton("Close", close_event))
    box.AddChild(pane)
    box.AddPythonFuncHandlerForInstance(App.ET_INPUT_CLOSE_MENU,
                                        "_tmp_infobox_close.CloseInfoBox")
    box.SetVisible()
    TacticalControlWindow.GetInstance().AddChild(box)
    return box


def test_close_click_hides_box_and_runs_handler():
    mod = _close_handler_module()
    try:
        box = _build_box()
        panel = InfoBoxPanel()
        panel.render_payload()                     # populates _boxes_by_id
        assert panel.dispatch_event("close:" + box._id) is True
        assert mod.closed == [box]                 # SDK close handler ran
        assert box.IsVisible() == 0                 # box hidden
        panel.invalidate()
        # Box no longer serialized once hidden.
        import json
        js = panel.render_payload()
        assert json.loads(js[len("setInfoBoxes("):-2])["entries"] == []
    finally:
        del sys.modules["_tmp_infobox_close"]


def test_stale_close_id_dropped():
    panel = InfoBoxPanel()
    panel.render_payload()
    assert panel.dispatch_event("close:nonexistent") is True


def test_non_close_action_not_handled():
    panel = InfoBoxPanel()
    assert panel.dispatch_event("expand:1") is False
