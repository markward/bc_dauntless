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


def test_set_zoom_target_uses_zoom_factor_for_fov():
    from engine.host_loop import _BridgeCamera
    cam = _BridgeCamera()
    cam.set_zoom_target((0.0, 5.0, 0.0), dt=999.0, snap=True, zoom_factor=0.45)
    _eye, _t, _up, fov = cam.compute_camera()
    # Fully zoomed (snap) FOV is base * zoom_factor, not base * _BRIDGE_ZOOM_MIN.
    from engine.host_loop import _BRIDGE_ZOOM_MAX
    assert abs(fov - cam.FOV_Y_RAD * 0.45) < 1e-6


def test_zoom_factor_resets_for_focus_without_officer_factor():
    from engine.host_loop import _BridgeCamera, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_MIN
    cam = _BridgeCamera()
    # 1) officer-menu zoom with an authored factor
    cam.set_zoom_target((0.0, 5.0, 0.0), dt=999.0, snap=True, zoom_factor=0.45)
    _e, _t, _u, fov1 = cam.compute_camera()
    assert abs(fov1 - cam.FOV_Y_RAD * 0.45) < 1e-6
    # 2) a later watch-target focus passes NO officer factor -> must NOT reuse 0.45
    cam.set_zoom_target((0.0, 9.0, 0.0), dt=999.0, snap=True)   # zoom_factor defaults None
    _e2, _t2, _u2, fov2 = cam.compute_camera()
    assert abs(fov2 - cam.FOV_Y_RAD * _BRIDGE_ZOOM_MIN) < 1e-6   # default, not 0.45
