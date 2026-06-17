"""Camera object surface that MissionLib.SetupBridgeSet drives."""
import App  # noqa: F401  (installs the SDK finder + shim namespace)
from engine.appc.bridge_set import (
    NiCameraData, CameraObjectClass_CreateFromNiCamera, CameraObjectClass_Create,
)


def test_create_from_nicamera_copies_frustum_and_placement():
    data = NiCameraData(
        position=(1.0, 2.0, 3.0),
        rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1),
        frustum=(-0.5, 0.5, 0.4, -0.4),
        near=1.0, far=800.0, source="x.nif",
    )
    cam = CameraObjectClass_CreateFromNiCamera(data, "maincamera")
    assert cam.position == (1.0, 2.0, 3.0)
    f = cam.GetNiFrustum()
    assert (f.m_fLeft, f.m_fRight, f.m_fTop, f.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)
    assert cam.GetNearDistance() == 1.0 and cam.GetFarDistance() == 800.0
    # orientation is a column-vector matrix: identity -> forward is +Y col.
    assert cam.orientation.GetCol(1).y == 1.0


def test_frustum_halving_round_trips_through_setter():
    data = NiCameraData((0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                        (-1.0, 1.0, 0.8, -0.8), 1.0, 800.0)
    cam = CameraObjectClass_CreateFromNiCamera(data, "maincamera")
    f = cam.GetNiFrustum()
    f.m_fLeft *= 0.5
    f.m_fRight *= 0.5
    f.m_fTop *= 0.5
    f.m_fBottom *= 0.5
    cam.SetNiFrustum(f)
    g = cam.GetNiFrustum()
    assert (g.m_fLeft, g.m_fRight, g.m_fTop, g.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)


def test_create_from_coords_builds_real_camera():
    cam = CameraObjectClass_Create(0, 50, 47, -1.55, 0, 0, 1, "maincamera")
    assert cam.position == (0, 50, 47)
    # angle-axis (-1.55 rad about +Z) -> a real rotation matrix, not identity.
    assert cam.orientation.GetCol(0).x != 1.0


def test_setupbridgeset_else_branch_with_embedded_camera(monkeypatch):
    import App
    import MissionLib
    from engine.appc import bridge_set

    data = NiCameraData((0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                        (-1.0, 1.0, 0.8, -0.8), 1.0, 800.0, "starbase.nif")
    monkeypatch.setattr(bridge_set.ModelManager, "CloneCamera",
                        lambda self, path: data)

    pSet = MissionLib.SetupBridgeSet("CamTestSet", "starbase.nif", -35, 65, -1.55)
    cam = pSet.GetCamera("maincamera")
    assert cam is not None
    f = cam.GetNiFrustum()
    # SetupBridgeSet halves each frustum side for the embedded-camera path.
    assert (f.m_fLeft, f.m_fRight, f.m_fTop, f.m_fBottom) == (-0.5, 0.5, 0.4, -0.4)


def test_setupbridgeset_fallback_branch_when_no_camera(monkeypatch):
    import App
    import MissionLib
    from engine.appc import bridge_set

    monkeypatch.setattr(bridge_set.ModelManager, "CloneCamera",
                        lambda self, path: None)
    pSet = MissionLib.SetupBridgeSet("CamTestSet2", "nocam.nif", -35, 65, -1.55)
    assert pSet.GetCamera("maincamera") is not None


def test_clonecamera_returns_none_without_host_module(monkeypatch):
    """Headless: the compiled host module is absent -> None (SDK fallback)."""
    import sys
    import App
    monkeypatch.setitem(sys.modules, "_dauntless_host", None)
    assert App.g_kModelManager.CloneCamera("data/Models/Sets/X/x.nif") is None


def test_clonecamera_wraps_binding_result(monkeypatch):
    import sys
    import types
    import App
    fake = types.ModuleType("_dauntless_host")
    fake.parse_set_camera = lambda p: {
        "position": (1.0, 2.0, 3.0),
        "rotation": (1, 0, 0, 0, 1, 0, 0, 0, 1),
        "frustum": (-0.5, 0.5, 0.4, -0.4),
        "near": 1.0, "far": 800.0,
    }
    monkeypatch.setitem(sys.modules, "_dauntless_host", fake)
    data = App.g_kModelManager.CloneCamera("data/Models/Sets/X/x.nif")
    assert data is not None
    assert data.position == (1.0, 2.0, 3.0)
    assert data.frustum == (-0.5, 0.5, 0.4, -0.4)
