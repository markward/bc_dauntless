# tests/host/test_bridge_cutscene_camera.py
"""A PlacementWatch aimed at the BRIDGE set drives the bridge camera, not the
exterior view. Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md"""
import pytest

import App
import Camera
from engine.appc.bridge_set import BridgeSet_Create, CameraObjectClass_Create
from engine.appc.camera_modes import PlacementMode
from engine.appc.math import TGPoint3
from engine.host_loop import _active_cutscene_camera, _bridge_cutscene_camera


@pytest.fixture
def bridge_slot():
    """Restore whatever "bridge" set and rendered-set name existed before."""
    mgr = App.g_kSetManager
    prior = mgr.GetSet("bridge")
    prior_rendered = mgr._rendered_set_name
    yield
    mgr.DeleteSet("bridge")
    if prior is not None:
        mgr.AddSet(prior, "bridge")
    mgr._rendered_set_name = prior_rendered


def _bridge_with_shot(cam_name="CutsceneCam", shoot=True):
    """A bridge set whose active camera `cam_name` holds a PlacementWatch from
    "ShotCam" at "Shot Head" (bridge-local coords, like E6M1's FelixCam2)."""
    b = BridgeSet_Create()
    App.g_kSetManager.AddSet(b, "bridge")
    eye = App.Waypoint_Create("ShotCam", "bridge", None)
    eye.SetTranslate(TGPoint3(-35.0, -142.0, 45.0))
    head = App.Waypoint_Create("Shot Head", "bridge", None)
    head.SetTranslate(TGPoint3(-25.0, -60.0, 60.0))
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, cam_name)
    b.AddCameraToSet(cam, cam_name)
    b.SetActiveCamera(cam_name)
    if shoot:
        # PlacementWatch("bridge", "Shot Head", "ShotCam") -> bSweep=0, bReplace=1
        Camera.Placement("ShotCam", "Shot Head", "bridge", 0, 1)
    return b, cam, eye, head


def test_exterior_camera_ignores_rendered_bridge_set(bridge_slot):
    # E6M1: ChangeRenderedSet("bridge") + PlacementWatch on the bridge. Today
    # this returns the bridge camera and the host draws SPACE through it.
    _bridge_with_shot()
    App.g_kSetManager.MakeRenderedSet("bridge")
    assert _active_cutscene_camera() is None


def test_bridge_cutscene_camera_finds_placement_on_cutscene_cam(bridge_slot):
    b, cam, eye, head = _bridge_with_shot()
    got = _bridge_cutscene_camera()
    assert got is not None
    assert got[0] is cam
    assert isinstance(got[1], PlacementMode)


def test_bridge_cutscene_camera_finds_placement_on_maincamera(bridge_slot):
    # E4M4 MissionFailDialog: PlacementWatch with no CutsceneCameraBegin lands
    # on the bridge's own maincamera.
    b, cam, eye, head = _bridge_with_shot(cam_name="maincamera")
    got = _bridge_cutscene_camera()
    assert got is not None and got[0] is cam


def test_bridge_cutscene_camera_works_without_rendered_bridge(bridge_slot):
    # E3M2 BerkeleyIntro & 5 others never ChangeRenderedSet("bridge").
    _bridge_with_shot()
    App.g_kSetManager.MakeRenderedSet("__some_space_set__")
    assert _bridge_cutscene_camera() is not None


def test_bridge_cutscene_camera_none_for_non_placement_mode(bridge_slot):
    # Only PlacementMode counts. A VALID non-Placement mode on the bridge
    # camera (ZoomTarget: real camera action, never aimed at the bridge by any
    # SDK mission) must be rejected by the TYPE gate. (The Galaxy seated
    # GalaxyBridgeCaptain mode is a PlaceByDirection attr bag whose IsValid()
    # is always 0 in our shim, so it cannot pin the type gate -- hence
    # ZoomTarget here.)
    b, cam, eye, head = _bridge_with_shot(shoot=False)
    Camera.ZoomTarget("ShotCam", "Shot Head", "bridge", 0, 1)
    assert cam.GetCurrentCameraMode().IsValid()      # precondition
    assert _bridge_cutscene_camera() is None


def test_bridge_cutscene_camera_none_for_invalid_placement(bridge_slot):
    b, cam, eye, head = _bridge_with_shot(shoot=False)
    mode = cam.GetNamedCameraMode("Placement")      # no Source => invalid
    cam.PushCameraMode(mode)
    assert _bridge_cutscene_camera() is None


def test_bridge_cutscene_camera_none_without_bridge_set(bridge_slot):
    App.g_kSetManager.DeleteSet("bridge")
    assert _bridge_cutscene_camera() is None


from engine.host_loop import _BridgeCamera, _sync_bridge_mode_pose


def test_sync_sets_bridge_pose_from_shot(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    eye, target, up, _ = cam.compute_camera()
    assert eye == (-35.0, -142.0, 45.0)              # at ShotCam
    # looking from ShotCam toward Shot Head (+X, +Y, +Z)
    assert target[0] > eye[0] and target[1] > eye[1] and target[2] > eye[2]


def test_sync_clears_when_shot_ends(bridge_slot):
    b, cam_obj, eye, head = _bridge_with_shot()
    cam = _BridgeCamera()
    base = cam.compute_camera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    App.g_kSetManager.DeleteSet("bridge")            # shot gone (camera removed)
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    assert cam.compute_camera() == base


def test_sync_clears_when_exterior_active(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    cam.set_mode_pose((9.0, 9.0, 9.0), (9.0, 10.0, 9.0), (0.0, 0.0, 1.0))
    base_cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=True, paused=False)
    assert cam.compute_camera() == base_cam.compute_camera()


def test_sync_paused_leaves_slot_untouched(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    held = ((1.0, 1.0, 1.0), (1.0, 2.0, 1.0), (0.0, 0.0, 1.0))
    cam.set_mode_pose(*held)
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=True)
    eye, target, up, _ = cam.compute_camera()
    assert (eye, target, up) == held
