"""The per-frame render sync binds live-pose PLANETS to the transform store
and draws every SHIP through the native interpolation buffer: nothing is
pushed as a Python-built matrix.

`_sync_instance_transforms` used to build a 16-float world matrix in Python
for every planet and every ship, every frame. Planets render at their LIVE
pose, so the renderer composes their matrix in C++ straight from the store.
Ships, the player included (live while manually flown, interpolated
otherwise), are tracked by the native buffer and drawn by one
`interp_compose` (phase 3c); no ship is ever bound to the store, which would
let the store sweep draw over the compose.

The bindings need the native module; here they are stubbed at the
engine.host_io seam so the decision logic is testable headlessly.
"""
import pytest

from engine import host_io, host_loop
from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.native_transform_buffer import NativeTransformBuffer


class _FakeRenderer:
    def __init__(self):
        self.pushed = []          # iids given an explicit matrix

    def set_world_transform(self, iid, mat):
        self.pushed.append(iid)

    def set_emissive_scale(self, iid, scale):
        pass

    def set_visible(self, iid, visible):
        pass

    def nebula_lightning_enabled(self):
        return False


class _Obj:
    """Store-backed object stand-in: what matters here is that it carries an
    `_xform` handle and a live pose."""

    def __init__(self, x=0.0):
        self._xform = (7, 1)
        self._loc = TGPoint3(x, 0.0, 0.0)
        self._rot = TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot

    def GetScale(self):
        return 1.0


@pytest.fixture
def bindings(monkeypatch):
    """Stub the native binding; record every (iid, index, generation, scale)."""
    calls = []

    def _stub(iid, index, generation, scale):
        calls.append((iid, index, generation, scale))
        return True

    monkeypatch.setattr(host_io, "set_instance_transform_slot", _stub)
    return calls


@pytest.fixture
def composed(monkeypatch):
    """Record the native interpolation calls the sync makes."""
    calls = []
    for name in ("interp_track", "interp_set_live", "interp_compose"):
        monkeypatch.setattr(
            host_io, name,
            lambda *a, _n=name: calls.append((_n,) + a))
    return calls


def _sync(renderer, session, player, **kw):
    host_loop._sync_instance_transforms(
        renderer, session, player, NativeTransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0, **kw)


def _scene_with_planet():
    player = _Obj()
    planet = _Obj(x=500.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.planet_instances[planet] = 2
    session.planet_natural_scale[planet] = 3.0
    session.player = player
    return session, player, planet


def test_player_at_its_live_pose_is_composed_not_bound_or_pushed(
        bindings, composed):
    r = _FakeRenderer()
    player = _Obj()
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.player = player

    _sync(r, session, player)

    assert bindings == [], "a composed ship must not be store-bound"
    assert r.pushed == []
    assert ("interp_track", 1, True, True) in composed
    assert ("interp_set_live", 1, True) in composed


def test_planets_are_bound_not_pushed(bindings, composed):
    r = _FakeRenderer()
    session, player, _planet = _scene_with_planet()

    _sync(r, session, player)

    assert bindings == [(2, 7, 1, 3.0)]
    assert r.pushed == []


def test_rebinding_is_skipped_while_nothing_changes(bindings, composed):
    """Steady state must not cross the boundary at all — that is the win."""
    r = _FakeRenderer()
    session, player, _planet = _scene_with_planet()

    _sync(r, session, player)
    _sync(r, session, player)
    _sync(r, session, player)

    assert len(bindings) == 1, "re-bound despite an unchanged slot and scale"


def test_scale_change_rebinds(bindings, composed):
    r = _FakeRenderer()
    session, player, planet = _scene_with_planet()

    _sync(r, session, player)
    planet.GetScale = lambda: 4.0
    _sync(r, session, player)

    assert bindings == [(2, 7, 1, 3.0), (2, 7, 1, 12.0)]


def test_no_ship_is_bound_or_pushed_in_either_player_mode(bindings, composed):
    """Interpolated or live, the player and every other ship are composed
    natively; none is pushed or bound."""
    r = _FakeRenderer()
    player = _Obj()
    other = _Obj(x=100.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player

    _sync(r, session, player, player_is_interpolated=False)
    _sync(r, session, player, player_is_interpolated=True)

    assert r.pushed == []
    assert bindings == []
    assert [c for c in composed if c[0] == "interp_track"] == [
        ("interp_track", 1, True, True), ("interp_track", 2, True, True)]
    assert [c for c in composed if c[0] == "interp_compose"] == [
        ("interp_compose", 0.5)] * 2
