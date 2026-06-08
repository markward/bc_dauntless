import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


def test_panel_starts_closed_and_payload_is_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    assert p.is_open() is False
    payload = p.render_payload()
    assert payload is not None and "setShipPropertyViewer" in payload
    assert _payload_data(payload)["visible"] is False


def test_open_builds_descriptors_and_payload_lists_subsystems(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.is_open() is True
    data = _payload_data(p.render_payload())
    assert data["visible"] is True
    assert data["pin_count"] == 1


def test_close_resets_and_emits_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open(); p.close()
    assert p.is_open() is False
    assert p.selected_index is None


def test_select_pin_sets_popover_payload(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy",
             "properties": {"name": "Phaser 1", "type": "PhaserBank"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_index == 0
    data = _payload_data(p.render_payload())
    assert data["selected"]["properties"]["type"] == "PhaserBank"


def test_reopen_with_same_pin_count_repushes(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.render_payload() is not None      # first push
    assert p.render_payload() is None          # unchanged → diffed out
    p.close()
    assert p.render_payload() is not None       # hide push
    p.open()                                     # reopen, same pin_count
    assert p.render_payload() is not None       # MUST re-push, not None


def test_camera_frames_ship_in_world_space_not_origin(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    # Two mounts ~500 GU from origin, 2 GU apart → centroid near (500,*,*),
    # fit distance driven by the 1 GU half-spread, NOT the 500 GU offset.
    fake = [{"name": "A", "world_pos": (500.0, 1.0, 0.0),
             "state": "healthy", "properties": {}, "icon_id": 6},
            {"name": "B", "world_pos": (500.0, -1.0, 0.0),
             "state": "healthy", "properties": {}, "icon_id": 6}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert abs(p.camera.target[0] - 500.0) < 1e-6
    assert p.camera.distance < 50.0   # framed to the cloud, not the 500 GU offset


def test_close_after_open_emits_hide_payload(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [{"name": "A", "world_pos": (0, 0, 0),
                                       "state": "healthy", "properties": {},
                                       "icon_id": 6}])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open(); p.render_payload()
    p.close()
    payload = p.render_payload()
    assert payload is not None
    assert '"visible": false' in payload.lower()


def test_deselect_noop_returns_false(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.render_payload()  # consume first push
    # deselect when nothing selected → no-op, no re-push
    assert p.dispatch_event("deselect") is False
    assert p.render_payload() is None  # snapshot unchanged → no spurious push
