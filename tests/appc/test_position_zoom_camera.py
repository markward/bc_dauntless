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
