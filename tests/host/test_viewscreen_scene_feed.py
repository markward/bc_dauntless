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
    def __init__(self, loc, radius=2.0, target=None, dying=False):
        self._loc, self._r, self._target, self._dying = loc, radius, target, dying

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return _Rot()

    def GetRadius(self):
        return self._r

    def GetTarget(self):
        return self._target

    def IsDying(self):
        return 1 if self._dying else 0


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


FWD_FOV = 1.0   # radians; the forward feed's FOV handed to the resolver


def test_none_when_no_target(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None


def test_auto_focus_on_player_target(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    assert out is not None
    eye, target, up, fov, near, far = out
    assert eye == (0.0, 0.0, 0.0)            # eye at player (Source)
    assert target[0] > 0.0 and abs(target[1]) < 1e-6   # looks at the target (+X)
    assert near == host_loop.VS_NEAR and far == host_loop.VS_FAR


# ── _viewscreen_fov: adaptive-fill FOV (pure function, tested directly) ────────
# forward_fov chosen generous (~69 deg) so mid-band cases stay well under it,
# never accidentally satisfied by the upper clamp.
BIG_FWD_FOV = 1.2   # radians


def test_viewscreen_fov_matches_formula_in_unclamped_band():
    # r=2, dist=20 -> r/dist=0.1 -> (0.1/0.6)=0.16666... -> 2*atan(...) ~= 0.3303 rad,
    # strictly between VS_FOV_MIN (~0.0698 rad) and BIG_FWD_FOV (1.2 rad).
    tgt = _Ship(_Pt(20.0, 0.0, 0.0), radius=2.0)
    eye = (0.0, 0.0, 0.0)
    fov = host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV)
    expected = 2.0 * math.atan((2.0 / 20.0) / host_loop.VS_TARGET_FILL)
    assert host_loop.VS_FOV_MIN < expected < BIG_FWD_FOV
    assert abs(fov - expected) < 1e-9


def test_viewscreen_fov_clamps_to_forward_fov_for_close_target():
    # r=100, dist=1 -> formula ~2.98 rad, must clamp to forward_fov.
    tgt = _Ship(_Pt(1.0, 0.0, 0.0), radius=100.0)
    eye = (0.0, 0.0, 0.0)
    fov = host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV)
    assert fov == BIG_FWD_FOV


def test_viewscreen_fov_clamps_to_fov_min_for_distant_target():
    # r=1, dist=100000 -> formula ~3.3e-5 rad, must clamp to VS_FOV_MIN.
    tgt = _Ship(_Pt(100000.0, 0.0, 0.0), radius=1.0)
    eye = (0.0, 0.0, 0.0)
    fov = host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV)
    assert abs(fov - host_loop.VS_FOV_MIN) < 1e-12


def test_viewscreen_fov_zero_distance_returns_forward_fov():
    tgt = _Ship(_Pt(0.0, 0.0, 0.0), radius=2.0)
    eye = (0.0, 0.0, 0.0)
    assert host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV) == BIG_FWD_FOV


def test_viewscreen_fov_zero_radius_returns_forward_fov():
    tgt = _Ship(_Pt(20.0, 0.0, 0.0), radius=0.0)
    eye = (0.0, 0.0, 0.0)
    assert host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV) == BIG_FWD_FOV


def test_resolver_fov_matches_viewscreen_fov_helper(wired):
    tgt = _Ship(_Pt(20.0, 0.0, 0.0), radius=2.0)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.016, BIG_FWD_FOV)
    assert out is not None
    eye, target, up, fov, near, far = out
    assert abs(fov - host_loop._viewscreen_fov(tgt, eye, BIG_FWD_FOV)) < 1e-9


def test_dead_target_falls_back_to_forward(wired):
    dead = _Ship(_Pt(500.0, 0.0, 0.0), dying=True)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=dead)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None


def test_mission_watch_object_overrides_player_target(wired):
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    # settle the "last seen player target" memory
    host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    # MissionLib.ViewscreenWatchObject writes a different object into the mode
    wired.GetNamedCameraMode("ViewscreenZoomTarget").SetAttrIDObject("Target", watched)
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    target = out[1]
    assert target[1] > 0.0 and abs(target[0]) < 1e-6   # watched (+Y), not combat (+X)


def test_changing_player_target_overwrites_mission_watch(wired):
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    wired.GetNamedCameraMode("ViewscreenZoomTarget").SetAttrIDObject("Target", watched)
    # BC: PlayerTargetChanged re-points the mode on the next target change.
    newtgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player._target = newtgt
    out = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)
    target = out[1]
    assert target[2] > 0.0 and abs(target[1]) < 1e-6   # new target (+Z), not watched (+Y)


def test_source_pinned_to_live_player(wired):
    tgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)[0] == (10.0, 20.0, 30.0)


def test_target_point_is_eye_plus_forward_not_bare_forward(wired):
    # player off-origin so eye+fwd != fwd; a bare `target = fwd` returns (0,0,1).
    tgt = _Ship(_Pt(10.0, 20.0, 130.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    target = host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV)[1]
    for got, want in zip(target, (10.0, 20.0, 31.0)):
        assert abs(got - want) < 1e-6


def test_invalid_mode_returns_none_not_fallback_pose(wired):
    # Dying player => ZoomTargetMode._ideal() -> None => IsValid() false.
    # Without the IsValid() guard, Update() would return a bogus fallback pose.
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt, dying=True)
    assert host_loop._viewscreen_scene_feed(player, 0.016, FWD_FOV) is None
