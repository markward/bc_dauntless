"""Tests for bridge set state and control flow."""
import os

from engine.appc.bridge_set import (
    ViewScreenObject, CameraObjectClass, _NiFrustum, off_texture_abs_path)
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


def test_set_off_texture_is_recorded_not_swallowed():
    # SetOffTexture used to fall through _LoudStub.__getattr__ as a no-op, so
    # MissionLib.ShowLoadingText's loading screen never reached the renderer.
    vs = ViewScreenObject("x.nif")
    assert vs.GetOffTexture() is None
    vs.SetOffTexture("data/Icons/ViewscreenLoading.tga")
    assert vs.GetOffTexture() == "data/Icons/ViewscreenLoading.tga"


def test_off_texture_abs_path_resolves_against_game_root():
    vs = ViewScreenObject("x.nif")
    assert off_texture_abs_path(vs) == ""
    assert off_texture_abs_path(None) == ""
    vs.SetOffTexture("data/Icons/ViewscreenLoading.tga")
    p = off_texture_abs_path(vs)
    assert p.endswith("game/data/Icons/ViewscreenLoading.tga")
    assert os.path.isabs(p)
