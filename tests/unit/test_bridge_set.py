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
