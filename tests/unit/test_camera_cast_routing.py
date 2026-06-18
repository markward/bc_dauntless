"""Regression: the bridge camera walk-on must actually ROUTE to the cutscene
controller, not just stop crashing.

The camera-move TGAnimAction is built inside
Bridge.Characters.CommonAnimations.WalkCameraToCaptOnD via
``pCamera = App.CameraObjectClass_Cast(pCharacter)`` then
``pCamera.GetAnimNode()``. If CameraObjectClass_Cast is unstubbed, App's
module-level ``__getattr__`` returns a ``_NamedStub`` whose ``__call__``
yields another ``_NamedStub`` — so ``pCamera`` is a stub, its anim node has no
``kind="camera"``, and the TGAnimAction instant-completes instead of calling
``request_camera_path``. The cutscene then silently never plays (no crash).

These tests pin both the cast itself and the end-to-end routing through the
real SDK ``WalkCameraToCaptOnD``. See
docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.
"""
import pytest

import engine.bridge_cutscene as bc
from engine.appc.bridge_set import (
    BridgeSet_Create, BridgeObjectClass_Create, ZoomCameraObjectClass_Create,
)


class _RecordingController:
    def __init__(self):
        self.camera = []
        self.door = []

    def request_camera_path(self, action, node, clip):
        self.camera.append((action, node, clip))

    def request_object_anim(self, action, node, clip):
        self.door.append((action, node, clip))


@pytest.fixture
def controller():
    ctrl = _RecordingController()
    bc.set_controller(ctrl)
    yield ctrl
    bc.clear_controller()


def test_camera_object_class_cast_returns_the_camera():
    import App
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    # Must be the REAL function — App's _NamedStub catch-all would return a
    # stub for any args, so identity-return for a camera proves it is real.
    assert App.CameraObjectClass_Cast(cam) is cam
    assert App.CameraObjectClass_Cast(None) is None
    assert App.CameraObjectClass_Cast(object()) is None


def test_walk_camera_to_capt_routes_camera_and_door(controller):
    import App
    import Bridge.Characters.CommonAnimations as CommonAnim

    # The door lines in WalkCameraToCaptOnD call GetSet("bridge").GetObject("bridge").
    bs = BridgeSet_Create()
    bridge_obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    bs.AddObjectToSet(bridge_obj, "bridge")
    prior = App.g_kSetManager.GetSet("bridge")
    App.g_kSetManager.AddSet(bs, "bridge")
    try:
        cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
        seq = CommonAnim.WalkCameraToCaptOnD(cam)
        seq.Play()
    finally:
        if prior is not None:
            App.g_kSetManager.AddSet(prior, "bridge")

    # The camera-move action requested the camera path (this is the bug fix).
    assert "WalkCameraToCaptD" in [c[2] for c in controller.camera]
    # The lift door requested the bridge object's embedded animation.
    assert any(d[2] == "DB_Door_L1" for d in controller.door)
