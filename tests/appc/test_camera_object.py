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


def _aims_at(cam, point, max_deg):
    """True when the camera's object-convention forward (col1) points within
    max_deg of `point`, with a level up (col2 ~ +Z)."""
    import math
    R = cam.orientation
    fwd, up = R.GetCol(1), R.GetCol(2)
    d = [point[i] - cam.position[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    cos_a = (fwd.x * d[0] + fwd.y * d[1] + fwd.z * d[2]) / n
    return up.z > 0.999 and cos_a > math.cos(math.radians(max_deg))


def test_fed_comm_cameras_face_the_captains_chair():
    """MissionLib.SetupBridgeSet's hardcoded D/E bridge comm cameras (their
    NIFs carry no camera) must look at the captain's chair, where a hailed
    captain sits (Soto: SovereignSeated on EBridgeSet, E2M0).

    Chair centres measured from the stock set NIFs (nif_shapes): DBridge
    "cmnd seat" (0.0, 86.3, 17.9); EBridge "chair captain" (-0.9, 141.5, 49.6).
    Reading the angle-axis forward as col1 aimed both cameras along +X at the
    side wall instead (the live bug)."""
    d_cam = CameraObjectClass_Create(0, 50, 47, -1.55, 0, 0, 1, "maincamera")
    e_cam = CameraObjectClass_Create(0, 95, 64, -1.55, 0, 0, 1, "maincamera")
    assert _aims_at(d_cam, (0.0, 86.3, 30.0), 45.0)
    assert _aims_at(e_cam, (-0.9, 141.5, 49.6), 20.0)
    # The SDK's -1.55 (not -pi/2) is the 1.2 degree trim onto the E chair's
    # off-centre x; the conversion must keep that sign.
    assert e_cam.orientation.GetCol(1).x < 0.0


def test_create_orientation_is_proper_rotation():
    import math
    # the SDK's own tilted unit axis (GalaxyBridge.CreateBridgeModel)
    cam = CameraObjectClass_Create(0, 0, 0, 0.7, -0.000665, -0.087559, 0.996159, "c")
    R = cam.orientation
    c0, c1, c2 = R.GetCol(0), R.GetCol(1), R.GetCol(2)
    cross = (c1.y * c2.z - c1.z * c2.y, c1.z * c2.x - c1.x * c2.z,
             c1.x * c2.y - c1.y * c2.x)
    # object convention: right = forward x up, det +1
    assert all(abs(cross[i] - (c0.x, c0.y, c0.z)[i]) < 1e-6 for i in range(3))
    assert abs(math.sqrt(c1.x ** 2 + c1.y ** 2 + c1.z ** 2) - 1.0) < 1e-6


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
