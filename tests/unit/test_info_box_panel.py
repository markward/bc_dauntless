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
