from engine.appc.bridge_set import (
    BridgeSet, BridgeSet_Create, BridgeSet_Cast,
    BridgeObjectClass_Create, ViewScreenObject_Create,
    ZoomCameraObjectClass_Create, ZoomCameraObjectClass_GetObject,
    ModelManager,
)
from engine.appc.sets import SetClass


def test_create_returns_bridgeset_and_is_a_setclass():
    pset = BridgeSet_Create()
    assert isinstance(pset, BridgeSet)
    assert isinstance(pset, SetClass)          # crew creation path works for real


def test_cast_returns_none_for_non_bridgeset():
    # Critical: the real Load() branches `if BridgeSet_Cast(...) == None:`.
    assert BridgeSet_Cast(None) is None
    assert BridgeSet_Cast(SetClass()) is None
    bs = BridgeSet_Create()
    assert BridgeSet_Cast(bs) is bs


def test_config_round_trips():
    bs = BridgeSet_Create()
    assert bs.IsSameConfig("GalaxyBridge") == 0     # nothing set yet
    bs.SetConfig("GalaxyBridge")
    assert bs.GetConfig() == "GalaxyBridge"
    assert bs.IsSameConfig("GalaxyBridge")          # truthy
    assert bs.IsSameConfig("SovereignBridge") == 0


def test_viewscreen_is_real_data_object_and_round_trips():
    bs = BridgeSet_Create()
    assert bs.GetViewScreen() is None
    vs = ViewScreenObject_Create("data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    # Carries the NIF path so the host can realize the screen mesh.
    assert vs.nif == "data/Models/Sets/DBridge/DBridgeViewScreen.nif"
    # Host fills this in; defaults to None.
    assert vs.render_instance is None
    # Feed state round-trips (consumed later by 5c/RTT). Off by default.
    assert vs.GetRemoteCam() is None
    vs.SetRemoteCam("cam-sentinel")
    assert vs.GetRemoteCam() == "cam-sentinel"
    vs.SetIsOn(1)
    assert vs.IsOn() == 1
    # SetViewScreen stores it.
    bs.SetViewScreen(vs, "viewscreen")
    assert bs.GetViewScreen() is vs
    # The unbuilt menu/handler surface still no-ops via the _LoudStub catch-all
    # (does not raise). IsStaticOn is now real (defaults to 0), but SetMenu
    # and ToggleRemoteCam remain no-ops.
    assert vs.SetMenu("whatever") is None
    assert vs.ToggleRemoteCam() is None
    assert vs.IsStaticOn() == 0


def test_delete_camera_from_set():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    bs.DeleteCameraFromSet("maincamera")
    assert bs.GetCamera("maincamera") is None


def test_bridge_object_is_real_pure_object():
    obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    # Carries the NIF path so the host can realize the mesh.
    assert obj.nif == "data/Models/Sets/DBridge/DBridge.nif"
    # Host fills this in; defaults to None.
    assert obj.render_instance is None
    # GalaxyBridge.CreateBridgeModel calls these — they record, don't raise.
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    obj.SetAngleAxisRotation(0.0, 1.0, 0.0, 0.0)
    assert obj.translate == (1.0, 2.0, 3.0)
    assert obj.rotation == (0.0, 1.0, 0.0, 0.0)
    # Property set stays truthy so DBridgeProperties.LoadPropertySet runs.
    assert obj.GetPropertySet() is not None


def test_zoom_camera_is_real_data_object_and_round_trips():
    cam = ZoomCameraObjectClass_Create(0.683736, 86.978439, 50.0,
                                       1.570796, -0.000665, -0.087559, 0.996159,
                                       "maincamera")
    assert cam.position == (0.683736, 86.978439, 50.0)
    assert cam.base_position == (0.683736, 86.978439, 50.0)
    assert cam.orientation == (1.570796, -0.000665, -0.087559, 0.996159)
    # Zoom params round-trip through the getters.
    cam.SetMinZoom(0.64); cam.SetMaxZoom(1.0); cam.SetZoomTime(0.375)
    assert cam.GetMinZoom() == 0.64
    assert cam.GetMaxZoom() == 1.0
    assert cam.GetZoomTime() == 0.375
    # ConfigureCharacters overrides .position (the popped-mode/cutscene anchor)
    # via SetTranslateXYZ; base_position (the captain mode BasePosition) is kept.
    cam.SetTranslateXYZ(0.683736, 86.978439, 61.934944)
    assert cam.position == (0.683736, 86.978439, 61.934944)
    assert cam.base_position == (0.683736, 86.978439, 50.0)
    # The remaining zoom-animation surface still no-ops via _LoudStub.
    assert cam.ToggleZoom(0.0) is None
    assert cam.Update(0.0) is None


def test_zoom_camera_mode_stack_round_trips():
    # The captain camera-mode stack is real: push/current/pop by object and by
    # name (E1M1 does PopCameraMode("GalaxyBridgeCaptain")).
    from engine.appc.camera_modes import CameraMode_Create
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    assert cam.GetCurrentCameraMode() is None
    mode = CameraMode_Create("PlaceByDirection", cam)
    mode._named = "GalaxyBridgeCaptain"
    assert cam.PushCameraMode(mode) is None
    assert cam.GetCurrentCameraMode() is mode
    assert cam.PopCameraMode("GalaxyBridgeCaptain") is mode
    assert cam.GetCurrentCameraMode() is None
    # Pushing None is a no-op (GalaxyBridge pushes GetNamedCameraMode(...) which
    # is None when no builder exists).
    assert cam.PushCameraMode(None) is None
    assert cam.GetCurrentCameraMode() is None


def test_camera_mode_create_holds_place_by_direction_attrs():
    # App.CameraMode_Create returns an attr-bag the SDK CameraModes.* builders
    # fill; the host harvests BasePosition/Movement/angles from it.
    from engine.appc.camera_modes import CameraMode_Create
    from engine.appc.math import TGPoint3
    mode = CameraMode_Create("PlaceByDirection", None)
    assert mode.kind == "PlaceByDirection"
    mode.SetAttrPoint("BasePosition", TGPoint3(0.683736, 86.978439, 50.0))
    mode.SetAttrPoint("Movement", TGPoint3(0.0, -15.0, 15.0))
    mode.SetAttrFloat("StartMoveAngle", 1.25)
    mode.SetAttrFloat("EndMoveAngle", 2.5)
    base = mode.GetAttrPoint("BasePosition")
    assert (base.x, base.y, base.z) == (0.683736, 86.978439, 50.0)
    mov = mode.GetAttrPoint("Movement")
    assert (mov.x, mov.y, mov.z) == (0.0, -15.0, 15.0)
    assert mode.GetAttrFloat("StartMoveAngle") == 1.25
    assert mode.GetAttrFloat("EndMoveAngle") == 2.5


def test_zoom_camera_get_object_returns_added_camera():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    assert ZoomCameraObjectClass_GetObject(bs, "maincamera") is cam


def test_model_manager_load_model_records_env():
    mm = ModelManager()
    # Records the texture/env path the SDK pre-loads each NIF with, returns None.
    assert mm.LoadModel("data/Models/Sets/DBridge/DBridge.nif", None,
                        "data/Models/Sets/DBridge/High/") is None
    assert mm.env_for("data/Models/Sets/DBridge/DBridge.nif") == \
        "data/Models/Sets/DBridge/High/"
    assert mm.env_for("missing.nif") is None


from engine.appc.anim_node import TGAnimNode
from engine.appc.actions import TGAnimPosition_Create


def test_camera_get_anim_node_is_real_and_does_not_crash():
    # Regression for the E1M1 Briefing() crash:
    # 'NoneType' object has no attribute 'UseAnimationPosition'.
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    node = cam.GetAnimNode()
    assert isinstance(node, TGAnimNode)
    assert node.kind == "camera"
    assert node.owner is cam
    assert cam.GetAnimNode() is node            # persistent
    node.UseAnimationPosition("WalkCameraToCaptD")   # must not raise
    assert node.position_clip == "WalkCameraToCaptD"


def test_bridge_object_get_anim_node_real_and_guest_chair_safe():
    obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    node = obj.GetAnimNode()
    assert isinstance(node, TGAnimNode)
    assert node.kind == "object"
    assert obj.GetAnimNode() is node            # persistent
    # PutGuestChairOut/In build a TGAnimPosition from the node — must work.
    pos = TGAnimPosition_Create(node, "db_guest_chair_out")
    assert pos.name == "db_guest_chair_out"


def test_viewscreen_records_static_state():
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    # defaults: static off, no group, zero variation
    assert vs.IsStaticOn() == 0
    assert vs._static_icon_group is None
    assert vs._static_min == 0.0
    assert vs._static_max == 0.0
    # SDK drives state on
    vs.SetStaticTextureIconGroup("View Screen Static")
    vs.SetStaticIsOn(1)
    vs.SetStaticVariation(0.8, 1)
    assert vs._static_icon_group == "View Screen Static"
    assert vs.IsStaticOn() == 1
    assert vs._static_min == 0.8
    assert vs._static_max == 1.0


def test_viewscreen_static_off_clears():
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    vs.SetStaticIsOn(1)
    vs.SetStaticIsOn(0)
    assert vs.IsStaticOn() == 0


def test_viewscreen_menu_methods_still_noop():
    # Deferred menu surface must keep falling through _LoudStub (no crash, None).
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    assert vs.SetMenu(object()) is None
    assert vs.MenuUp() is None
