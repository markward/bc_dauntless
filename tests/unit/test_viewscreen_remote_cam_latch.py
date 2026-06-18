"""Interim comm-feed hold on ViewScreenObject.SetRemoteCam.

Once a real comm-set camera (CameraObjectClass) is showing on the viewscreen,
a SetRemoteCam that would replace it with a non-camera placeholder is ignored,
so the comm scene stays visible. This compensates for two engine gaps:

  * MissionLib.ViewscreenOff reverts the remote cam to Game.GetPlayerCamera(),
    which is an unimplemented stub here (not a real camera), and
  * the action-sequence timing gap fires ViewscreenOff immediately after
    ViewscreenOn (no dialogue delay).

A real camera still replaces the current one, so legitimate camera changes
(e.g. switching to another comm set's maincamera) work. This hold is interim;
it goes away once action-sequence timing lands and ViewscreenOff reverts after
the dialogue with a real player camera.
"""
from engine.appc.bridge_set import ViewScreenObject, CameraObjectClass, _NiFrustum
from engine.appc.math import TGMatrix3


def _cam():
    return CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                             _NiFrustum(), 1.0, 800.0)


def test_remote_cam_holds_when_reverted_to_non_camera():
    vs = ViewScreenObject("x.nif")
    cam = _cam()
    vs.SetRemoteCam(cam)

    class _PlayerCamStub:        # stands in for the unimplemented player camera
        pass
    vs.SetRemoteCam(_PlayerCamStub())     # ViewscreenOff-style revert — ignored
    assert vs.GetRemoteCam() is cam


def test_remote_cam_replaced_by_a_real_camera():
    vs = ViewScreenObject("x.nif")
    c1, c2 = _cam(), _cam()
    vs.SetRemoteCam(c1)
    vs.SetRemoteCam(c2)                   # real camera DOES replace
    assert vs.GetRemoteCam() is c2


def test_remote_cam_initial_set_accepts_non_camera():
    # No comm camera showing yet -> a non-camera is accepted (no hold to honor).
    vs = ViewScreenObject("x.nif")
    vs.SetRemoteCam(None)
    assert vs.GetRemoteCam() is None
