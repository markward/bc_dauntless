"""Tests for bridge set state and control flow."""
from engine.appc.bridge_set import ViewScreenObject, CameraObjectClass, _NiFrustum
from engine.appc.math import TGMatrix3


def test_set_remote_cam_is_plain_passthrough():
    vs = ViewScreenObject("x.nif")
    cam = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)
    vs.SetRemoteCam(cam)

    class _PlayerCamStub:  # ViewscreenOff reverts to a non-camera player stub
        pass
    stub = _PlayerCamStub()
    vs.SetRemoteCam(stub)                       # no hold: revert is honored
    assert vs.GetRemoteCam() is stub


def test_set_remote_cam_real_camera_replaces_previous():
    vs = ViewScreenObject("x.nif")
    c1 = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                           _NiFrustum(), 1.0, 800.0)
    c2 = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                           _NiFrustum(), 1.0, 800.0)
    vs.SetRemoteCam(c1)
    vs.SetRemoteCam(c2)
    assert vs.GetRemoteCam() is c2


def test_set_remote_cam_initial_none_is_stored():
    vs = ViewScreenObject("x.nif")
    vs.SetRemoteCam(None)
    assert vs.GetRemoteCam() is None
