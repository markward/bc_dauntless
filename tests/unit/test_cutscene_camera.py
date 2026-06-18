"""Tests for the in-space cutscene-camera SDK plumbing.

Covers the two Layer-1 defects that made Actions/CameraScriptActions.py
silently fail:

  1. CameraObjectClass.SetMatrixRotation was missing — it fell through
     _LoudStub.__getattr__ to a silent no-op, so CutsceneCameraBegin
     (CameraScriptActions.py:154) never copied the active camera's rotation
     onto the new cutscene camera.
  2. App.CameraObjectClass_GetObject was missing — it fell through App.py's
     module __getattr__ to a *truthy* _NamedStub, so the cutscene Get/End/
     camera-mode functions (and WarpSequence.py) thought they had a camera
     when they had a fake stub.
"""
import App
from engine.appc.bridge_set import (
    CameraObjectClass,
    CameraObjectClass_Create,
    CameraObjectClass_GetObject,
    _NiFrustum,
)
from engine.appc.math import TGMatrix3, TGPoint3


def _rot_yaw(angle):
    """A non-identity column-vector rotation about Z (yaw)."""
    return TGMatrix3().MakeRotation(angle, TGPoint3(0.0, 0.0, 1.0))


# ── SetMatrixRotation round-trip ──────────────────────────────────────────────

def test_set_matrix_rotation_stores_matrix_as_is():
    cam = CameraObjectClass("CutsceneCam", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)
    R = _rot_yaw(0.7)
    cam.SetMatrixRotation(R)
    # GetWorldRotation returns the stored orientation; round-trip every element.
    out = cam.GetWorldRotation()
    for c in range(3):
        oc, rc = out.GetCol(c), R.GetCol(c)
        assert abs(oc.x - rc.x) < 1e-9
        assert abs(oc.y - rc.y) < 1e-9
        assert abs(oc.z - rc.z) < 1e-9


def test_set_matrix_rotation_is_real_not_loudstub_noop():
    """Regression: the method must exist on the class, not resolve via
    _LoudStub.__getattr__ (which returns a no-op lambda)."""
    assert "SetMatrixRotation" in vars(CameraObjectClass)


# ── CameraObjectClass_GetObject ───────────────────────────────────────────────

def test_get_object_returns_the_added_camera():
    s = App.SetClass_Create()
    cam = CameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    assert CameraObjectClass_GetObject(s, "CutsceneCam") is cam


def test_get_object_missing_camera_is_falsey():
    """A real miss must be falsey so SDK `if not pCamera: return 0` guards fire
    (the old _NamedStub fallthrough was truthy and broke those guards)."""
    s = App.SetClass_Create()
    assert not CameraObjectClass_GetObject(s, "NoSuchCam")


def test_app_exports_get_object_not_a_named_stub():
    """App.CameraObjectClass_GetObject must be the real shim, not App.py's
    truthy _NamedStub catch-all."""
    s = App.SetClass_Create()
    cam = CameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "CutsceneCam")
    s.AddCameraToSet(cam, "CutsceneCam")
    assert App.CameraObjectClass_GetObject(s, "CutsceneCam") is cam


# ── CutsceneCameraBegin / End end-to-end on a real set ────────────────────────

def _fresh_bridge_set(name="bridge"):
    s = App.BridgeSet_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def test_cutscene_camera_begin_copies_active_camera_pose():
    import Actions.CameraScriptActions as CSA
    s = _fresh_bridge_set("cutscene_test_set")
    active = CameraObjectClass_Create(5, -40, 65, 0, 0, 0, 1, "maincamera")
    active.SetMatrixRotation(_rot_yaw(0.9))
    active.SetTranslate(TGPoint3(11.0, 22.0, 33.0))
    s.AddCameraToSet(active, "maincamera")
    s.SetActiveCamera("maincamera")

    # Must run without raising and without silently no-op'ing the rotation copy.
    CSA.CutsceneCameraBegin(None, "cutscene_test_set")

    cut = s.GetCamera("CutsceneCam")
    assert cut is not None
    assert s.GetActiveCamera() is cut
    # Position copied from the active camera (CameraScriptActions.py:155).
    assert cut.GetWorldLocation().x == 11.0
    assert cut.GetWorldLocation().y == 22.0
    assert cut.GetWorldLocation().z == 33.0
    # Rotation copied from the active camera (CameraScriptActions.py:154) — the
    # defect being fixed. Compare against the active camera's matrix.
    a = active.GetWorldRotation()
    c = cut.GetWorldRotation()
    for col in range(3):
        ac, cc = a.GetCol(col), c.GetCol(col)
        assert abs(cc.x - ac.x) < 1e-9
        assert abs(cc.y - ac.y) < 1e-9
        assert abs(cc.z - ac.z) < 1e-9

    App.g_kSetManager.DeleteSet("cutscene_test_set")


def test_cutscene_camera_end_removes_camera():
    import Actions.CameraScriptActions as CSA
    s = _fresh_bridge_set("cutscene_end_set")
    active = CameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    s.AddCameraToSet(active, "maincamera")
    s.SetActiveCamera("maincamera")

    CSA.CutsceneCameraBegin(None, "cutscene_end_set")
    assert s.GetCamera("CutsceneCam") is not None

    CSA.CutsceneCameraEnd(None, "cutscene_end_set")
    assert s.GetCamera("CutsceneCam") is None

    App.g_kSetManager.DeleteSet("cutscene_end_set")
