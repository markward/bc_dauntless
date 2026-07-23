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
    # "watch_ctrl.resolve_target_world(r)" appears only at the inlined call
    # site; "_active_zoom_officer(crew_menu_panel, r)" also appears earlier,
    # inside _active_zoom_officer_world's own definition -- search for the
    # menu-zoom fallback AFTER the watch-target resolve so this compares the
    # two lines at the actual call site, not the unrelated helper def.
    watch_idx = src.index("watch_ctrl.resolve_target_world(r)")
    menu_idx = src.index("_active_zoom_officer(crew_menu_panel, r)", watch_idx)
    assert watch_idx < menu_idx


def test_watch_singleton_roundtrip():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    assert bcw.get_controller() is ctrl
    bcw.clear_controller()
    assert bcw.get_controller() is None
