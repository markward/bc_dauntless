"""SPV effective position + subsystem SetPosition persistence."""
import json

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


class _FakeTarget:
    def __init__(self): self.written = None
    def write(self, leaf, edits): self.written = (leaf, list(edits))


def _panel_with_one_subsystem(monkeypatch, baked_pos=(0.0, 1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": baked_pos, "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "icon_id": 2,
    }]
    return p


def test_effective_pos_prefers_pending_then_saved_then_baked(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch, baked_pos=(0.0, 1.0, 0.0))
    assert p._effective_pos(0) == (0.0, 1.0, 0.0)
    p._saved_pos[0] = (0.0, 2.0, 0.0)
    assert p._effective_pos(0) == (0.0, 2.0, 0.0)
    p._pending_pos[0] = (0.0, 3.0, 0.0)
    assert p._effective_pos(0) == (0.0, 3.0, 0.0)


def test_set_subsystem_position_stages_pending_and_counts(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch)
    p.set_subsystem_position(0, (1.5, 1.0, 0.0))
    assert p._pending_pos[0] == (1.5, 1.0, 0.0)
    payload = _payload_data(p.render_payload())
    assert payload["pending_count"] == 1


def test_save_routes_setposition(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch)
    tgt = _FakeTarget()
    monkeypatch.setattr(
        "engine.ui.ship_property_viewer_panel.resolve_override_target",
        lambda ship: tgt)
    monkeypatch.setattr(
        "engine.ui.ship_property_viewer_panel.hardpoint_leaf_for_ship",
        lambda ship: "galaxy")
    p.set_subsystem_position(0, (1.5, 1.0, 0.0))
    assert p.dispatch_event("save") is True
    assert tgt.written is not None
    leaf, edits = tgt.written
    assert ("Center Impulse", "SetPosition", (1.5, 1.0, 0.0)) in edits
    # Saved value retained for in-session preview; no longer pending.
    assert p._pending_pos == {}
    assert p._saved_pos[0] == (1.5, 1.0, 0.0)
