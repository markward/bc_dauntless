"""SPV transform-tool radio state."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    # render_payload() returns a JS call string, e.g.
    # "setShipPropertyViewer({...});" — mirrors tests/ui/test_ship_property_viewer_panel.py.
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


def _panel():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    return p


def test_default_tool_is_none():
    assert _panel().active_tool is None


def test_set_tool_activates_and_toggles_off():
    p = _panel()
    assert p.dispatch_event("set_tool:transform") is True
    assert p.active_tool == "transform"
    # Selecting the active tool again clears it.
    assert p.dispatch_event("set_tool:transform") is True
    assert p.active_tool is None


def test_set_tool_is_mutually_exclusive():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    p.dispatch_event("set_tool:rotate")
    assert p.active_tool == "rotate"


def test_unknown_tool_rejected():
    p = _panel()
    assert p.dispatch_event("set_tool:bogus") is False
    assert p.active_tool is None


def test_render_payload_carries_active_tool():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    payload = _payload_data(p.render_payload())
    assert payload["active_tool"] == "transform"


def test_close_resets_tool():
    p = _panel()
    p.dispatch_event("set_tool:scale")
    p.close()
    assert p.active_tool is None
