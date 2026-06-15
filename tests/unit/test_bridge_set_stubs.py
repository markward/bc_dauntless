import engine.appc._stub_trace as st
from engine.appc.bridge_set import (
    BridgeSet, BridgeSet_Create, BridgeSet_Cast,
    BridgeObjectClass_Create, ViewScreenObject_Create,
    ZoomCameraObjectClass_Create, ZoomCameraObjectClass_GetObject,
    ModelManager,
)
from engine.appc.sets import SetClass


def setup_function(_):
    st.reset()


def test_create_returns_bridgeset_and_is_a_setclass():
    pset = BridgeSet_Create()
    assert isinstance(pset, BridgeSet)
    assert isinstance(pset, SetClass)          # crew creation path works for real
    assert "BridgeSet_Create" in st.fired()


def test_cast_returns_none_for_non_bridgeset():
    # Critical: the real Load() branches `if BridgeSet_Cast(...) == None:`.
    assert BridgeSet_Cast(None) is None
    assert BridgeSet_Cast(SetClass()) is None
    bs = BridgeSet_Create()
    assert BridgeSet_Cast(bs) is bs


def test_config_round_trips_and_is_same_config():
    bs = BridgeSet_Create()
    assert bs.IsSameConfig("GalaxyBridge") == 0     # nothing set yet
    bs.SetConfig("GalaxyBridge")
    assert bs.GetConfig() == "GalaxyBridge"
    assert bs.IsSameConfig("GalaxyBridge")          # truthy
    assert bs.IsSameConfig("SovereignBridge") == 0


def test_viewscreen_round_trips():
    bs = BridgeSet_Create()
    assert bs.GetViewScreen() is None
    vs = ViewScreenObject_Create("vs.nif")
    bs.SetViewScreen(vs, "viewscreen")
    assert bs.GetViewScreen() is vs


def test_bridge_object_is_real_pure_object():
    obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    # No longer a loud stub — must drop off the bridge-stub summary.
    assert "BridgeObjectClass_Create" not in st.fired()
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


def test_camera_stub_supports_sdk_calls():
    cam = ZoomCameraObjectClass_Create(0.0, 1.0, 2.0, 1.57, 0.0, 0.0, 1.0, "maincamera")
    cam.SetMinZoom(0.64)
    cam.SetMaxZoom(1.0)
    cam.SetZoomTime(0.375)
    cam.PushCameraMode(cam.GetNamedCameraMode("GalaxyBridgeCaptain"))
    cam.Update(0.0)
    cam.SetTranslateXYZ(0.0, 1.0, 2.0)
    assert "ZoomCameraObjectClass_Create" in st.fired()


def test_camera_get_object_returns_added_camera():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    assert ZoomCameraObjectClass_GetObject(bs, "maincamera") is cam


def test_model_manager_load_model_records_env_and_is_not_loud():
    mm = ModelManager()
    # Real now: records the texture/env path, returns None, and is NOT a
    # loud stub (it must drop off the bridge-stub summary in step 3).
    assert mm.LoadModel("data/Models/Sets/DBridge/DBridge.nif", None,
                        "data/Models/Sets/DBridge/High/") is None
    assert "g_kModelManager.LoadModel" not in st.fired()
    assert mm.env_for("data/Models/Sets/DBridge/DBridge.nif") == \
        "data/Models/Sets/DBridge/High/"
    assert mm.env_for("missing.nif") is None
