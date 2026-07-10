import math

import engine.host_loop as hl


class _Cam:  # stand-in for CameraObjectClass
    pass


class _VS:
    def __init__(self, on, cam):
        self._on, self._cam = on, cam

    def IsOn(self):
        return self._on

    def GetRemoteCam(self):
        return self._cam


# ── _active_comm_feed ────────────────────────────────────────────────────────

def test_active_comm_feed_resolves_set_from_remote_cam(monkeypatch):
    import App as _App
    from engine.appc.sets import SetClass
    _App.g_kSetManager._sets.clear()
    cam = _Cam()
    s = SetClass(); s.SetName("StarbaseSet")
    s.AddCameraToSet(cam, "maincamera")
    _App.g_kSetManager.AddSet(s, "StarbaseSet")

    class _C:
        comm_set_ids = {"StarbaseSet": 3}
        viewscreen_obj = _VS(on=1, cam=cam)
    res = hl._active_comm_feed(_C())
    assert res is not None
    set_id, out_cam = res
    assert set_id == 3 and out_cam is cam


def test_active_comm_feed_none_when_remote_cam_is_not_a_set_maincamera():
    import App as _App
    _App.g_kSetManager._sets.clear()

    class _C:
        comm_set_ids = {}
        viewscreen_obj = _VS(on=1, cam=_Cam())
    assert hl._active_comm_feed(_C()) is None


def test_active_comm_feed_none_when_viewscreen_off():
    import App as _App
    from engine.appc.sets import SetClass
    _App.g_kSetManager._sets.clear()
    cam = _Cam()
    s = SetClass(); s.SetName("StarbaseSet")
    s.AddCameraToSet(cam, "maincamera")
    _App.g_kSetManager.AddSet(s, "StarbaseSet")

    class _C:
        comm_set_ids = {"StarbaseSet": 3}
        viewscreen_obj = _VS(on=0, cam=cam)   # off -> forward fallback
    assert hl._active_comm_feed(_C()) is None


def test_active_comm_feed_none_when_no_viewscreen():
    class _C:
        comm_set_ids = {}
        viewscreen_obj = None
    assert hl._active_comm_feed(_C()) is None


def test_active_comm_feed_none_when_set_has_no_assigned_id():
    # The remote cam IS a set's maincamera, but that set was never assigned a
    # comm_set_id (e.g. it carried no renderable comm instances) -> forward.
    import App as _App
    from engine.appc.sets import SetClass
    _App.g_kSetManager._sets.clear()
    cam = _Cam()
    s = SetClass(); s.SetName("StarbaseSet")
    s.AddCameraToSet(cam, "maincamera")
    _App.g_kSetManager.AddSet(s, "StarbaseSet")

    class _C:
        comm_set_ids = {}                      # no id for StarbaseSet
        viewscreen_obj = _VS(on=1, cam=cam)
    assert hl._active_comm_feed(_C()) is None


# ── _comm_camera_params ──────────────────────────────────────────────────────

def test_comm_camera_params_from_camera_object():
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    # Identity orientation: forward = +Y (col 1), up = +Z (col 2).
    orient = TGMatrix3()  # identity
    frustum = _NiFrustum(left=-1.0, right=1.0, top=0.75, bottom=-0.75,
                         near=1.0, far=800.0)
    cam = CameraObjectClass("maincamera", (10.0, 20.0, 30.0), orient,
                            frustum, 1.0, 800.0)
    eye, target, up, fov, near, far = hl._comm_camera_params(cam)
    assert eye == (10.0, 20.0, 30.0)
    assert target == (10.0, 21.0, 30.0)        # eye + forward(+Y)
    assert up == (0.0, 0.0, 1.0)               # +Z
    assert near == 1.0 and far == 800.0
    # fov_y = 2*atan(((top-bottom)/2)/near) = 2*atan(0.75)
    assert abs(fov - 2.0 * math.atan(0.75)) < 1e-9


def test_comm_camera_params_degenerate_frustum_falls_back():
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    cam = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)   # all-zero frustum
    eye, target, up, fov, near, far = hl._comm_camera_params(cam)
    assert fov > 0.0                                     # sane default, not 0


# ── _comm_feed_view (authored orientation + degenerate fallback) ─────────────

def test_comm_feed_view_uses_authored_orientation_not_bounds():
    """The authored camera orientation frames the shot; the aim-at-centre
    bounds are IGNORED when the orientation is valid (the interim hack removed)."""
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3, TGPoint3
    orient = TGMatrix3()
    orient.SetCol(0, TGPoint3(1.0, 0.0, 0.0))       # right
    orient.SetCol(1, TGPoint3(0.0, 1.0, 0.0))       # forward = +Y
    orient.SetCol(2, TGPoint3(0.0, 0.0, 1.0))       # up = +Z
    cam = CameraObjectClass("maincamera", (5.0, 5.0, 5.0), orient,
                            _NiFrustum(-1.0, 1.0, 0.75, -0.75, 1.0, 800.0),
                            1.0, 800.0)
    # bounds centre is somewhere else entirely; it must NOT be used.
    eye, target, up, fov, near, far = hl._comm_feed_view(
        cam, lambda: (99.0, 99.0, 99.0, 50.0))
    assert eye == (5.0, 5.0, 5.0)
    assert target == (5.0, 6.0, 5.0)                # eye + forward(+Y), not bounds
    assert up == (0.0, 0.0, 1.0)                    # authored up, not (0,0,1) hack-default


def test_comm_feed_view_falls_back_to_bounds_when_orientation_degenerate():
    """A zero/uninitialised orientation yields no view direction; the feed
    then aims at the comm room geometry centre so the set is still framed."""
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    zero = TGMatrix3().MakeZero()                   # degenerate: no basis
    cam = CameraObjectClass("maincamera", (5.0, 5.0, 5.0), zero,
                            _NiFrustum(-1.0, 1.0, 0.75, -0.75, 1.0, 800.0),
                            1.0, 800.0)
    eye, target, up, fov, near, far = hl._comm_feed_view(
        cam, lambda: (1.0, 2.0, 3.0, 50.0))
    assert eye == (5.0, 5.0, 5.0)
    assert target == (1.0, 2.0, 3.0)                # aimed at bounds centre
    assert up == (0.0, 0.0, 1.0)


def test_comm_feed_view_degenerate_with_no_bounds_keeps_authored():
    """Degenerate orientation AND no bounds available -> return the (degenerate)
    authored tuple unchanged rather than crashing."""
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    zero = TGMatrix3().MakeZero()
    cam = CameraObjectClass("maincamera", (5.0, 5.0, 5.0), zero,
                            _NiFrustum(-1.0, 1.0, 0.75, -0.75, 1.0, 800.0),
                            1.0, 800.0)
    eye, target, up, fov, near, far = hl._comm_feed_view(cam, lambda: None)
    assert eye == (5.0, 5.0, 5.0)
    assert target == (5.0, 5.0, 5.0)                # eye + zero-forward, no crash


# ── CameraObjectClass activation methods (folded-in fix) ─────────────────────

def test_camera_object_survives_activation_calls():
    # CameraScriptActions.SetCameraPositionAndFacing / CutsceneCameraBegin call
    # SetTranslate + AlignToVectors + UpdateNodeOnly on a CameraObjectClass
    # during the viewscreen/dock activation event chain. These must not raise
    # (an AttributeError there is swallowed by characters.SendActivationEvent,
    # killing the whole activation and the comm feed).
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3, TGPoint3
    cam = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)
    cam.SetTranslate(TGPoint3(5.0, 6.0, 7.0))
    assert tuple(cam.position) == (5.0, 6.0, 7.0)
    cam.AlignToVectors(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    # column-vector: col 1 = forward (+Y), col 2 = up (+Z)
    fwd = cam.orientation.GetCol(1)
    up = cam.orientation.GetCol(2)
    assert abs(fwd.y - 1.0) < 1e-9
    assert abs(up.z - 1.0) < 1e-9
    assert cam.UpdateNodeOnly() is None          # no-op, no scene-graph node


def test_camera_object_camera_mode_surface_no_ops():
    # GetNamedCameraMode / PushCameraMode are called by the SDK activation chain
    # (ViewscreenOn). Without _LoudStub fallthrough, CameraObjectClass raises
    # AttributeError, which characters.SendActivationEvent swallows — aborting
    # the chain before SetRemoteCam fires and the comm feed never engages.
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum
    from engine.appc.math import TGMatrix3
    cam = CameraObjectClass("maincamera", (0.0, 0.0, 0.0), TGMatrix3(),
                            _NiFrustum(), 1.0, 800.0)
    # These must return None (falsey), not raise — SDK guards with `if pMode:`
    # (unregistered name; "ViewscreenZoomTarget" is now a real _MODE_FACTORY
    # entry — see test_viewscreen_zoom_target_mode.py)
    assert cam.GetNamedCameraMode("NotARegisteredMode") is None
    assert cam.PushCameraMode(None) is None
    # truthy + isinstance checks must still hold
    assert bool(cam)
    assert isinstance(cam, CameraObjectClass)


def test_camera_object_world_transform_getters():
    # CutsceneCameraBegin (CameraScriptActions.py:158) calls GetWorldLocation /
    # GetWorldRotation. These should return the real stored placement data.
    from engine.appc.bridge_set import CameraObjectClass, _NiFrustum, CameraObjectClass_Create
    from engine.appc.math import TGMatrix3, TGPoint3
    cam = CameraObjectClass_Create(1.0, 2.0, 3.0, 0, 0, 0, 1, "maincamera")
    loc = cam.GetWorldLocation()
    assert hasattr(loc, "x") and hasattr(loc, "y") and hasattr(loc, "z")
    assert (loc.x, loc.y, loc.z) == (1.0, 2.0, 3.0)
    rot = cam.GetWorldRotation()
    assert rot is cam.orientation
