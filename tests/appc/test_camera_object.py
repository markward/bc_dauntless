"""Camera object surface that MissionLib.SetupBridgeSet drives."""
import App  # noqa: F401  (installs the SDK finder + shim namespace)
from engine.appc.bridge_set import (
    NiCameraData, CameraObjectClass_CreateFromNiCamera, CameraObjectClass_Create,
)


def _approx(p, expected, tol=1e-3):
    return (abs(p.x - expected[0]) < tol and abs(p.y - expected[1]) < tol
            and abs(p.z - expected[2]) < tol)


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
    # orientation is converted from the Gamebryo NiCamera frame to the BC-object
    # convention (col1=forward, col2=up). A BC-era set camera views down its
    # local +X with up = local +Y (see the factory docstring), so for an
    # identity NiCamera object-forward is world +X and object-up is world +Y.
    assert _approx(cam.orientation.GetCol(1), (1.0, 0.0, 0.0))   # forward = +gbCol0 (local +X)
    assert _approx(cam.orientation.GetCol(2), (0.0, 1.0, 0.0))   # up = +gbCol1 (local +Y)


def test_create_from_nicamera_converts_gamebryo_view_axis_to_object_forward():
    """A BC-era NetImmerse set camera's NIF node frame (columns = world images
    of local +X/+Y/+Z) VIEWS DOWN LOCAL +X with up = local +Y. The documented
    Gamebryo-1.2 -Z view axis does NOT hold for BC content: on the real Liu
    hail it pointed the camera at a side wall (live-refuted 2026-06-18), while
    +gbCol0 frames the seated admiral. CameraObjectClass.orientation is the
    BC-object convention (col0=right, col1=forward, col2=up; see AlignToVectors),
    so the factory converts with a cyclic column shift:
        forward = +gbCol0, up = +gbCol1, right = +gbCol2  (gbCol0 × gbCol1 = gbCol2).

    Input is the real maincamera rotation from
    data/Models/Sets/StarbaseControl/starbasecontrolRM.nif (E1M1 Liu hail),
    row-major. forward (+gbCol0 ≈ world +Y) aims from eye toward the room/Liu;
    up (+gbCol1 ≈ world +Z) is level."""
    rot = (0.1477, 0.0094, 0.9890,
           0.9762, -0.1619, -0.1442,
           0.1588, 0.9868, -0.0330)
    data = NiCameraData((-18.594, -41.858, 37.277), rot,
                        (-0.6941, 0.6941, 0.6941, -0.6941), 1.0, 5000.0)
    cam = CameraObjectClass_CreateFromNiCamera(data, "maincamera")
    # gbCol0=(0.1477,0.9762,0.1588), gbCol1=(0.0094,-0.1619,0.9868),
    # gbCol2=(0.9890,-0.1442,-0.0330).
    assert _approx(cam.orientation.GetCol(1), (0.1477, 0.9762, 0.1588))    # forward = +gbCol0
    assert _approx(cam.orientation.GetCol(2), (0.0094, -0.1619, 0.9868))   # up = +gbCol1
    assert _approx(cam.orientation.GetCol(0), (0.9890, -0.1442, -0.0330))  # right = +gbCol2
    # near/far carry through from the NIF (not the Create-path defaults).
    assert cam.GetNearDistance() == 1.0 and cam.GetFarDistance() == 5000.0


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
