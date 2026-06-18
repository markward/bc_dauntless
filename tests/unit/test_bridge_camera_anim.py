from engine.host_loop import _BridgeCamera, _ViewModeController


def test_anim_pose_overrides_compute_and_freezes_mouse_look():
    cam = _BridgeCamera()
    base_eye, _, _, _ = cam.compute_camera()
    cam.set_anim_pose((1.0, 2.0, 3.0), (1.0, 3.0, 3.0), (0.0, 0.0, 1.0))
    eye, target, up, fov = cam.compute_camera()
    assert eye == (1.0, 2.0, 3.0)
    assert target == (1.0, 3.0, 3.0)
    assert up == (0.0, 0.0, 1.0)
    assert fov > 0.0
    # Mouse-look frozen while the anim pose is active.
    before = (cam.yaw_rad, cam.pitch_rad)
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) == before
    # Clearing restores normal mouse-look behaviour.
    cam.clear_anim_pose()
    restored_eye, _, _, _ = cam.compute_camera()
    assert restored_eye == base_eye
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) != before


def test_view_mode_set_bridge():
    vm = _ViewModeController()
    vm.toggle()                # -> exterior (default is bridge)
    assert vm.is_exterior
    vm.set_bridge()
    assert vm.is_bridge
