import inspect
import engine.host_loop as HL
import engine.bridge_camera_watch as bcw


def test_host_loop_constructs_and_wires_watch_controller():
    src = inspect.getsource(HL)
    # Constructed + registered as the singleton alongside the walk controller.
    assert "BridgeCameraWatchController(" in src
    assert "set_watch_ctrl(" in src or "set_controller" in src
    # Reset on mission swap (next to walk_ctrl.reset()).
    assert "watch_ctrl.reset()" in src
    # Drives the camera via the watch-target-over-menu-zoom precedence, now
    # inlined at the zoom call site (Task 8 folded _resolve_bridge_focus_world's
    # body directly into the loop; see tests/unit/test_bridge_camera_zoom.py
    # and the resolver's former docstring, preserved as a comment there).
    # The watch target must be resolved and checked BEFORE falling through to
    # the crew-menu zoom-to-officer -- that ordering IS the precedence.
    # "watch_ctrl.resolve_target_world(r)" and "_active_zoom_officer(
    # crew_menu_panel, r)" both appear only at their inlined call sites (the
    # `_active_zoom_officer_world` thin wrapper was retired -- final-review
    # FIX 3, zero production callers) -- search for the menu-zoom fallback
    # AFTER the watch-target resolve so this compares the two call sites in
    # their actual precedence order.
    watch_idx = src.index("watch_ctrl.resolve_target_world(r)")
    menu_idx = src.index("_active_zoom_officer(crew_menu_panel, r)", watch_idx)
    assert watch_idx < menu_idx


def test_watch_singleton_roundtrip():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    assert bcw.get_controller() is ctrl
    bcw.clear_controller()
    assert bcw.get_controller() is None


def test_host_loop_sets_engaged_char_from_watch_ctrl():
    # Regression (final-review FIX 1): a watch-first engagement (fresh
    # session, _last_engaged_char still [None]) must give the resolver a
    # driver character, or MenuEventHandler is never called and the
    # maincamera never zooms. Assert the wiring exists at the watch-branch
    # call site, immediately after the target resolves.
    src = inspect.getsource(HL)
    watch_idx = src.index("watch_ctrl.resolve_target_world(r)")
    getter_idx = src.index("watch_ctrl.watched_character()", watch_idx)
    menu_idx = src.index("_active_zoom_officer(crew_menu_panel, r)", watch_idx)
    assert watch_idx < getter_idx < menu_idx


class _R:
    def __init__(self, center):
        self._c = center

    def get_instance_head_center(self, iid):
        return self._c


def test_watch_first_engagement_reaches_camera_engage(monkeypatch):
    # Regression (final-review FIX 1), runtime version: with
    # _last_engaged_char == [None] (fresh session, no prior officer/hail
    # engagement) and a watch target resolving, the driver character must be
    # the watched character (via the new watched_character() getter), and
    # routing it through MenuEventHandler -> ZoomCameraObjectClass.engage
    # must actually zoom the maincamera in and frame the watched world point.
    import App
    from engine.appc.bridge_set import ZoomCameraObjectClass
    from engine.appc.characters import CharacterClass_Create

    cam = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    cam.SetMinZoom(0.64)
    cam.SetMaxZoom(1.0)
    cam.SetZoomTime(0.375)

    class _Bridge:
        def GetCamera(self, name):
            return cam if name == "maincamera" else None

    class _SM:
        def GetSet(self, name):
            return _Bridge() if name == "bridge" else None

    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)

    ctrl = bcw.BridgeCameraWatchController()
    watched = CharacterClass_Create("", "")
    watched._render_instance = 7
    ctrl.watch(watched)

    _last_engaged_char = [None]              # fresh session, no prior engagement
    _engaged, _look_at, _engaged_char = False, None, None
    _w = ctrl.resolve_target_world(_R((10.0, 0.0, 0.0)))
    if _w is not None:
        _engaged, _look_at = True, _w
        _engaged_char = ctrl.watched_character()

    _drv = _engaged_char or _last_engaged_char[0]
    assert _drv is watched
    _drv.MenuEventHandler(_engaged, _look_at, 0.64)

    assert cam.IsZoomed() == 1
    assert cam.look_at == (10.0, 0.0, 0.0)
