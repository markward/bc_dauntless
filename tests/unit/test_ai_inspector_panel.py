"""Tests for AIInspectorPanel — the dev-only live AI-tree inspector modal.

Mirrors test_developer_options_panel.py / test_ship_property_viewer_panel.py:
open/close, render_payload snapshot-diff + hide payload, dispatch_event
cancel, name, invalidate.
"""
import json

import App
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc import ai as ai_mod
from engine.ui.ai_inspector_panel import AIInspectorPanel


def _body(payload):
    return json.loads(payload[len("setAIInspector("):-2])


def _seed_one_ship_with_ai():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    ship.SetAI(ai_mod.SequenceAI_Create(ship, "Root"))
    pSet.AddObjectToSet(ship, "ship_1")
    ship.SetName("Enterprise")  # AddObjectToSet overwrites name with identifier
    return ship


# ---- identity / open-close ------------------------------------------------

def test_name_is_ai_inspector():
    assert AIInspectorPanel().name == "ai-inspector"


def test_initially_closed():
    assert AIInspectorPanel().is_open() is False


def test_open_close_round_trip():
    p = AIInspectorPanel()
    p.open()
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


# ---- render_payload -------------------------------------------------------

def test_render_payload_none_when_closed_initially():
    p = AIInspectorPanel()
    assert p.render_payload() is None


def test_render_payload_shape_when_open():
    _seed_one_ship_with_ai()
    p = AIInspectorPanel()
    p.open()
    body = _body(p.render_payload())
    assert body["visible"] is True
    names = [s["ship_name"] for s in body["ships"]]
    assert "Enterprise" in names
    enterprise = next(s for s in body["ships"] if s["ship_name"] == "Enterprise")
    assert enterprise["tree"]["name"] == "Root"


def test_render_payload_dedups():
    _seed_one_ship_with_ai()
    p = AIInspectorPanel()
    p.open()
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_render_payload_close_emits_hide_once():
    _seed_one_ship_with_ai()
    p = AIInspectorPanel()
    p.open()
    p.render_payload()
    p.close()
    out = p.render_payload()
    assert _body(out) == {"visible": False}
    assert p.render_payload() is None


def test_invalidate_re_emits():
    _seed_one_ship_with_ai()
    p = AIInspectorPanel()
    p.open()
    first = p.render_payload()
    assert p.render_payload() is None
    p.invalidate()
    assert p.render_payload() == first


# ---- dispatch_event -------------------------------------------------------

def test_dispatch_cancel_closes():
    p = AIInspectorPanel()
    p.open()
    assert p.dispatch_event("cancel") is True
    assert p.is_open() is False


def test_dispatch_unknown_returns_false():
    p = AIInspectorPanel()
    p.open()
    assert p.dispatch_event("bogus") is False


def test_handle_key_esc_closes():
    p = AIInspectorPanel()
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False
