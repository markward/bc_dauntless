"""Layered hull damage, phase 2 (near/far): on the bridge viewscreen only the
feed's TARGET gets decks and rooms behind its holes. The host loop pushes that
target's render instance id (from the session's ship -> instance map) every
frame, or -1 when the viewscreen frames no target; the native interior policy
(renderer/hull_interior_policy.h) reads it for the viewscreen render."""
import pytest

import engine.renderer as renderer
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


class _Recorder:
    def __init__(self):
        self.pushed = []

    def set_viewscreen_target_instance(self, iid):
        self.pushed.append(iid)


@pytest.fixture
def wired(monkeypatch):
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")
    monkeypatch.setattr(host_loop, "Game_GetCurrentGame", lambda: _Game(cam))
    return cam


def test_target_pushes_its_instance_id(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    tgt_iid, player_iid = object(), object()      # stand-ins for native InstanceIds
    feed = host_loop._viewscreen_scene_feed(player, 0.61)
    assert feed is not None
    rec = _Recorder()
    host_loop._push_viewscreen_target(rec, feed, {player: player_iid, tgt: tgt_iid})
    assert rec.pushed == [tgt_iid]


def test_no_target_pushes_minus_one(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    feed = host_loop._viewscreen_scene_feed(player, 0.61)
    assert feed is None
    rec = _Recorder()
    host_loop._push_viewscreen_target(rec, feed, {player: object()})
    assert rec.pushed == [-1]


def test_unrealised_target_pushes_minus_one(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    feed = host_loop._viewscreen_scene_feed(player, 0.61)
    rec = _Recorder()
    host_loop._push_viewscreen_target(rec, feed, {player: object()})
    assert rec.pushed == [-1]


def test_wrapper_passes_through(monkeypatch):
    calls = []

    class _FakeHost:
        def set_viewscreen_target_instance(self, iid):
            calls.append(iid)

    monkeypatch.setattr(renderer, "_h", _FakeHost())
    marker = object()
    renderer.set_viewscreen_target_instance(marker)
    renderer.set_viewscreen_target_instance(-1)
    assert calls == [marker, -1]
    assert "set_viewscreen_target_instance" in renderer._REQUIRED_BINDINGS


def test_native_binding_takes_an_instance_id_or_minus_one():
    h = renderer._h
    h.set_viewscreen_target_instance(h.InstanceId())
    h.set_viewscreen_target_instance(-1)
    with pytest.raises(TypeError):
        h.set_viewscreen_target_instance(5)
