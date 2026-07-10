import pytest
from engine import host_loop
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


def test_none_when_no_target(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    assert host_loop._viewscreen_scene_feed(player, 0.61) is None


def test_dead_target_returns_none(wired):
    dead = _Ship(_Pt(500.0, 0.0, 0.0), dying=True)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=dead)
    assert host_loop._viewscreen_scene_feed(player, 0.61) is None


def test_fov_equals_forward_fov(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out1 = host_loop._viewscreen_scene_feed(player, 0.61)
    assert out1 is not None
    assert out1[3] == 0.61
    out2 = host_loop._viewscreen_scene_feed(player, 1.20)
    assert out2 is not None
    assert out2[3] == 1.20


def test_eye_is_behind_target_not_at_player(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0), radius=2.0)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.61)
    assert out is not None
    eye = out[0]
    # eye sits close BEHIND the target on the ship->target axis, not at the
    # player origin: eye.x is well past the midpoint toward the target.
    assert eye[0] > 250.0
    assert abs(eye[1]) < 1e-6
    assert abs(eye[2]) < 1e-6


def test_auto_focus_follows_player_target(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(player, 0.61)
    assert out is not None
    eye, look_at, up, fov, near, far = out
    assert near == host_loop.VS_NEAR and far == host_loop.VS_FAR
    assert fov == 0.61
    # look-at is further toward the target than the eye (framing it, not
    # looking back at the player).
    assert look_at[0] > eye[0]


def test_mission_watch_overrides_player_target(wired):
    combat = _Ship(_Pt(500.0, 0.0, 0.0), radius=2.0)
    other = _Ship(_Pt(0.0, 800.0, 0.0), radius=2.0)
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    # settle the "last seen player target" memory
    host_loop._viewscreen_scene_feed(player, 0.61)
    # MissionLib.ViewscreenWatchObject writes a different object into the mode
    wired.GetNamedCameraMode("ViewscreenZoomTarget").SetAttrIDObject("Target", other)
    out = host_loop._viewscreen_scene_feed(player, 0.61)
    assert out is not None
    eye = out[0]
    # eye is near `other` (0, 800, 0), not near the player's combat target.
    assert eye[1] > 400.0
    assert abs(eye[0]) < 1e-6
