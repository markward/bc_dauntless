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
    # Drives the camera via the focus resolver (not the raw menu-zoom call).
    assert "_resolve_bridge_focus_world(" in src


def test_watch_singleton_roundtrip():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    assert bcw.get_controller() is ctrl
    bcw.clear_controller()
    assert bcw.get_controller() is None
