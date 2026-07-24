from engine.appc.characters import CharacterClass


def test_officer_zoom_factor_from_location():
    from engine.host_loop import _officer_zoom_factor
    ch = CharacterClass()
    ch.SetLocation("DBHelm")
    ch.AddPositionZoom("DBHelm", 0.45, "Helm")
    assert _officer_zoom_factor(ch) == 0.45


def test_officer_zoom_factor_miss_is_sentinel():
    from engine.host_loop import _officer_zoom_factor
    from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL
    ch = CharacterClass()
    ch.SetLocation("DBHelm")                 # no AddPositionZoom
    assert _officer_zoom_factor(ch) == POSITION_ZOOM_SENTINEL


def _rigged_cam(monkeypatch):
    """A _BridgeCamera reading a fresh ZoomCameraObjectClass wired into
    hl._BRIDGE_ZOOM_CAM -- the MenuEventHandler port set_zoom_target used to
    own directly (see tests/unit/test_bridge_camera_zoom.py for the geometry
    coverage; this file only exercises the officer zoom_factor plumbing)."""
    import engine.host_loop as hl
    from engine.host_loop import _BridgeCamera
    from engine.appc.bridge_set import ZoomCameraObjectClass
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_EYE", (0.0, 0.0, 0.0))
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_MOVE", None)
    zoom_cam = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    zoom_cam.SetMinZoom(0.64); zoom_cam.SetMaxZoom(1.0); zoom_cam.SetZoomTime(0.375)
    monkeypatch.setattr(hl, "_BRIDGE_ZOOM_CAM", zoom_cam)
    return _BridgeCamera(), zoom_cam


def test_set_zoom_target_uses_zoom_factor_for_fov(monkeypatch):
    bc, zoom_cam = _rigged_cam(monkeypatch)
    zoom_cam.engage(0.45, (0.0, 5.0, 0.0))
    zoom_cam.advance(999.0)   # ease to completion
    _eye, _t, _up, fov = bc.compute_camera()
    # Fully zoomed FOV is base * zoom_factor, not base * _BRIDGE_ZOOM_MIN.
    assert abs(fov - bc.FOV_Y_RAD * 0.45) < 1e-6


def test_zoom_factor_resets_for_focus_without_officer_factor(monkeypatch):
    from engine.host_loop import _BRIDGE_ZOOM_MIN
    bc, zoom_cam = _rigged_cam(monkeypatch)
    # 1) officer-menu zoom with an authored factor
    zoom_cam.engage(0.45, (0.0, 5.0, 0.0))
    zoom_cam.advance(999.0)
    _e, _t, _u, fov1 = bc.compute_camera()
    assert abs(fov1 - bc.FOV_Y_RAD * 0.45) < 1e-6
    # 2) a later watch-target focus engages with the default min factor --
    # engage() always takes the caller's factor verbatim, so it must NOT
    # reuse the stale 0.45 from the prior officer-menu engagement (that
    # persistence bug lived in the old set_zoom_target).
    zoom_cam.engage(_BRIDGE_ZOOM_MIN, (0.0, 9.0, 0.0))
    zoom_cam.advance(999.0)
    _e2, _t2, _u2, fov2 = bc.compute_camera()
    assert abs(fov2 - bc.FOV_Y_RAD * _BRIDGE_ZOOM_MIN) < 1e-6   # default, not 0.45
