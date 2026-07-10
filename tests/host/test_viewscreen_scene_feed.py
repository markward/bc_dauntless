import math
import pytest
from engine import host_loop
from engine.core import game as game_mod
from engine.appc.bridge_set import CameraObjectClass_Create


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Rot:
    # column-vector: col2 = up (0,0,1)
    def GetCol(self, i):
        return _Pt(0.0, 0.0, 1.0) if i == 2 else _Pt(0.0, 1.0, 0.0)


class _Ship:
    def __init__(self, loc, radius=2.0, target=None):
        self._loc, self._r, self._target = loc, radius, target

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return _Rot()

    def GetRadius(self):
        return self._r

    def GetTarget(self):
        return self._target

    def IsDying(self):
        return 0


class _Game:
    def __init__(self, cam):
        self._cam = cam

    def GetPlayerCamera(self):
        return self._cam


@pytest.fixture
def wired(monkeypatch):
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")
    monkeypatch.setattr(host_loop, "Game_GetCurrentGame", lambda: _Game(cam))
    return cam


def test_none_when_not_engaged(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    assert host_loop._viewscreen_scene_feed(player, 0.016, False) is None


def test_hold_zoom_uses_player_target(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, True)
    assert out is not None
    eye, target, up, fov, near, far = out
    assert eye == (0.0, 0.0, 0.0)                       # eye at player (Source)
    # looks toward the target (+X): target = eye + forward
    assert target[0] > 0.0 and abs(target[1]) < 1e-6
    assert near == host_loop.VS_NEAR and far == host_loop.VS_FAR
    assert host_loop.VS_FOV_MIN <= fov <= host_loop.VS_FOV_MAX


def test_hold_with_no_target_is_none(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    assert host_loop._viewscreen_scene_feed(player, 0.016, True) is None


def test_mission_sticky_engages_without_hold(wired):
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    mode = wired.GetNamedCameraMode("ViewscreenZoomTarget")
    mode.SetAttrIDObject("Target", watched)
    wired.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")   # engage
    out = host_loop._viewscreen_scene_feed(player, 0.016, False)
    assert out is not None
    _eye, target, _up, _fov, _n, _f = out
    assert target[1] > 0.0                              # looks toward watched (+Y)


def test_mission_sticky_wins_over_hold_target(wired):
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    mode = wired.GetNamedCameraMode("ViewscreenZoomTarget")
    mode.SetAttrIDObject("Target", watched)
    wired.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")
    out = host_loop._viewscreen_scene_feed(player, 0.016, True)
    _eye, target, _up, _fov, _n, _f = out
    assert target[1] > 0.0 and abs(target[0]) < 1e-6    # watched (+Y), not combat (+X)


def test_source_pinned_to_live_player(wired):
    tgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, True)
    eye = out[0]
    assert eye == (10.0, 20.0, 30.0)                    # eye follows the live player


def test_target_point_is_eye_plus_forward_not_bare_forward(wired):
    # Player at a NON-ORIGIN location so `eye + fwd != fwd` numerically.
    # Target placed straight along +Z from the player so fwd is a clean unit
    # vector (0,0,1); eye + fwd must then be (10,20,31), NOT (0,0,1). A
    # regression `target = fwd` (dropping the `eye +`) would return (0,0,1)
    # here instead of (10.0, 20.0, 31.0), and this assertion catches it.
    tgt = _Ship(_Pt(10.0, 20.0, 130.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, True)
    assert out is not None
    eye, target, _up, _fov, _n, _f = out
    assert eye == (10.0, 20.0, 30.0)
    assert target[0] == pytest.approx(10.0, abs=1e-6)
    assert target[1] == pytest.approx(20.0, abs=1e-6)
    assert target[2] == pytest.approx(31.0, abs=1e-6)


def test_invalid_mode_returns_none_not_fallback_pose(wired):
    # ZoomTargetMode._ideal() returns None when its pinned Source dies. The
    # resolver pins Source = player, so a dying player invalidates the mode
    # even though the target is alive (proving this exercises the
    # `if not mode.IsValid(): return None` guard, not the earlier
    # `_target_alive(tgt)` check on the target).
    #
    # Without the IsValid() guard, mode.Update(dt) does NOT return None for
    # an invalid mode — it returns a bogus FALLBACK pose
    # ((0,0,0), (0,1,0), (0,0,1)) — so `out` would be a real tuple instead of
    # None, silently leaking that fallback pose to the renderer.
    class _DyingShip(_Ship):
        def IsDying(self):
            return 1

    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _DyingShip(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, True)
    assert out is None
