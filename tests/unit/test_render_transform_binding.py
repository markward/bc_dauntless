"""The per-frame render sync binds live-pose instances to the transform store
instead of pushing a matrix for them.

`_sync_instance_transforms` used to build a 16-float world matrix in Python for
the player and every planet, every frame. Those objects render at their LIVE
pose, so the renderer can compose the matrix in C++ straight from the store —
the point of Task 6. Render-INTERPOLATED instances (every non-player ship, and
the player while a helm AI flies it) still push, because their drawn pose is a
lerp of two sim snapshots and the store holds only the live one.

The binding itself needs the native module; here it is stubbed at the
engine.host_io seam so the decision logic is testable headlessly.
"""
import pytest

from engine import host_io, host_loop
from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.transform_buffer import TransformBuffer


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


def _sync(renderer, session, player, **kw):
    host_loop._sync_instance_transforms(
        renderer, session, player, TransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0, **kw)


def test_player_at_its_live_pose_is_bound_not_pushed(bindings):
    r = _FakeRenderer()
    player = _Obj()
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.player = player

    _sync(r, session, player)

    assert bindings == [(1, 7, 1, 2.0)]
    assert r.pushed == [], "a bound instance must not also be pushed"


def test_planets_are_bound_not_pushed(bindings):
    r = _FakeRenderer()
    player = _Obj()
    planet = _Obj(x=500.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.planet_instances[planet] = 2
    session.planet_natural_scale[planet] = 3.0
    session.player = player

    _sync(r, session, player)

    assert (2, 7, 1, 3.0) in bindings
    assert r.pushed == []


def test_rebinding_is_skipped_while_nothing_changes(bindings):
    """Steady state must not cross the boundary at all — that is the win."""
    r = _FakeRenderer()
    player = _Obj()
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.player = player

    _sync(r, session, player)
    _sync(r, session, player)
    _sync(r, session, player)

    assert len(bindings) == 1, "re-bound despite an unchanged slot and scale"


def test_scale_change_rebinds(bindings):
    r = _FakeRenderer()
    player = _Obj()
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.player = player

    _sync(r, session, player)
    player.GetScale = lambda: 4.0
    _sync(r, session, player)

    assert bindings == [(1, 7, 1, 2.0), (1, 7, 1, 8.0)]


def test_interpolated_player_is_unbound_and_pushed(bindings):
    """A helm AI flying the player renders the interpolated pose; leaving the
    instance bound would let the store sweep overwrite it."""
    r = _FakeRenderer()
    player = _Obj()
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.player = player

    _sync(r, session, player)                       # manual: bound
    _sync(r, session, player,
          player_interp_pose=(TGPoint3(1.0, 2.0, 3.0), TGMatrix3()))

    assert bindings == [(1, 7, 1, 2.0), (1, -1, 0, 1.0)]
    assert r.pushed == [1]


def test_non_player_ships_still_push_the_interpolated_matrix(bindings):
    r = _FakeRenderer()
    player = _Obj()
    other = _Obj(x=100.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player

    _sync(r, session, player)

    assert r.pushed == [2], "non-player ships render interpolated, so they push"
    assert bindings == [(1, 7, 1, 2.0)], "and must never be bound"
