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


def test_export_writes_the_live_tree_to_a_fixed_path(tmp_path, monkeypatch):
    """The export exists to make a live capture durable: the bug being chased
    is 'NPCs stop firing after the first volley', which does not reproduce
    headlessly, so the only record of the AI's state is whatever the panel was
    showing at that moment.

    A FIXED filename, deliberately overwritten: the debug loop is fly ->
    observe -> export -> read, and a timestamped file per press turns that into
    a directory to sift through.
    """
    from engine.ui import ai_inspector_panel as mod

    target = tmp_path / "ai_inspector_export.json"
    monkeypatch.setattr(mod, "EXPORT_PATH", target)
    monkeypatch.setattr(mod, "collect_all_ship_ai",
                        lambda: [{"ship_name": "Enemy 1", "tree": {"type": "PriorityListAI"}}])

    panel = mod.AIInspectorPanel()
    panel.open()
    assert panel.dispatch_event("export") is True

    assert target.is_file(), "export produced no file"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert [s["ship_name"] for s in data["ships"]] == ["Enemy 1"]
    assert data["ships"][0]["tree"]["type"] == "PriorityListAI"


def test_export_captures_the_same_data_the_panel_renders(tmp_path, monkeypatch):
    """Export must go through collect_all_ship_ai, not a parallel path.

    Otherwise enriching the model (walk cadence, memo pinning) improves what is
    on screen and silently leaves the exported file behind -- and the file is
    the half that gets read later, away from the running game.
    """
    from engine.ui import ai_inspector_panel as mod

    calls = []

    def _spy():
        calls.append(1)
        return [{"ship_name": "S", "tree": {}, "future_field": 42}]

    monkeypatch.setattr(mod, "EXPORT_PATH", tmp_path / "e.json")
    monkeypatch.setattr(mod, "collect_all_ship_ai", _spy)

    panel = mod.AIInspectorPanel()
    panel.open()
    panel.dispatch_event("export")

    assert calls, "export did not use the panel's own model"
    data = json.loads((tmp_path / "e.json").read_text(encoding="utf-8"))
    assert data["ships"][0]["future_field"] == 42, (
        "export dropped a field the model supplied")


def test_export_overwrites_rather_than_appending(tmp_path, monkeypatch):
    from engine.ui import ai_inspector_panel as mod

    target = tmp_path / "ai_inspector_export.json"
    monkeypatch.setattr(mod, "EXPORT_PATH", target)
    monkeypatch.setattr(mod, "collect_all_ship_ai", lambda: [{"ship_name": "A"}])
    panel = mod.AIInspectorPanel()
    panel.open()
    panel.dispatch_event("export")

    monkeypatch.setattr(mod, "collect_all_ship_ai", lambda: [{"ship_name": "B"}])
    panel.dispatch_event("export")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert [s["ship_name"] for s in data["ships"]] == ["B"]


def test_export_failure_does_not_take_the_panel_down(tmp_path, monkeypatch):
    """A read-only directory or a locked file must not kill the panel mid-fight
    -- losing the inspector is worse than losing one export."""
    from engine.ui import ai_inspector_panel as mod

    monkeypatch.setattr(mod, "EXPORT_PATH", tmp_path / "nope" / "deep" / "e.json")
    monkeypatch.setattr(mod, "collect_all_ship_ai", lambda: [{"ship_name": "A"}])
    panel = mod.AIInspectorPanel()
    panel.open()

    def _boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(mod.Path, "write_text", _boom, raising=False)
    assert panel.dispatch_event("export") is True   # handled, did not raise
    assert panel.is_open()


def test_every_action_the_markup_fires_is_handled_by_the_panel(tmp_path, monkeypatch):
    """A button wired to an action nothing handles fails SILENTLY -- the click
    lands, dispatch_event returns False, and the panel just sits there. Nothing
    logs, so it reads as 'the export did nothing' rather than 'the export was
    never wired'. Pins the markup against the handler.
    """
    import re
    from pathlib import Path as _P
    from engine.ui import ai_inspector_panel as mod
    from engine.ui.ai_inspector_panel import AIInspectorPanel

    # Redirect the export: this test dispatches every action for real, and the
    # export action writes a file. A test that litters the project root is a
    # test that changes the thing it runs in.
    monkeypatch.setattr(mod, "EXPORT_PATH", tmp_path / "export.json")

    html = (_P(__file__).resolve().parents[2]
            / "native" / "assets" / "ui-cef" / "index.html").read_text(encoding="utf-8")
    section = re.search(r'<section id="ai-inspector-panel".*?</section>', html, re.S)
    assert section, "no #ai-inspector-panel section"

    actions = set(re.findall(r"dauntlessEvent\('ai-inspector/([^']+)'\)",
                             section.group(0)))
    assert "export" in actions, "the Export button is not in the markup"
    assert "cancel" in actions

    panel = AIInspectorPanel()
    panel.open()
    unhandled = [a for a in sorted(actions) if not panel.dispatch_event(a)]
    assert not unhandled, f"markup fires actions the panel ignores: {unhandled}"
