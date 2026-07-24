"""The render-pose provider feeds the camera and the renderer the SAME
per-ship pose, so both draw/track identical positions (smooth-motion fix).

Policy:
- Non-player ships integrate on the 60 Hz sim tick → always render-interpolated.
- The player ship renders LIVE while manually flown (integrated per render
  frame, already smooth), but must be interpolated when a helm-AI / waypoint
  order drives it (then it too moves on the 60 Hz tick).
"""
import pytest


class _FakeShip:
    def __init__(self, loc_xyz):
        from engine.appc.math import TGPoint3, TGMatrix3
        self._loc = TGPoint3(*loc_xyz)
        self._rot = TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


class _FakeSession:
    def __init__(self, mapping):
        self.ship_instances = mapping


def _buffer_with(iid, prev_xyz, cur_xyz):
    from engine.core.transform_buffer import TransformBuffer
    from engine.appc.math import TGPoint3, TGMatrix3
    buf = TransformBuffer()
    buf.set_current(iid, TGPoint3(*prev_xyz), TGMatrix3())  # seeds prev=cur
    buf.roll()                                              # prev = first
    buf.set_current(iid, TGPoint3(*cur_xyz), TGMatrix3())  # cur = second
    return buf


def test_non_player_ship_is_interpolated():
    from engine.host_loop import _make_render_pose_provider
    target = _FakeShip((0.0, 0.0, 0.0))
    buf = _buffer_with(7, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    session = _FakeSession({target: 7})

    pose_of = _make_render_pose_provider(
        session, buf, 0.5, interpolate_player=False, player_iid=99)
    loc, rot = pose_of(target)
    assert loc.x == pytest.approx(5.0)  # midpoint of prev(0) and cur(10)


def test_player_is_live_when_manually_flown():
    from engine.host_loop import _make_render_pose_provider
    player = _FakeShip((3.0, 0.0, 0.0))
    buf = _buffer_with(1, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    session = _FakeSession({player: 1})

    pose_of = _make_render_pose_provider(
        session, buf, 0.5, interpolate_player=False, player_iid=1)
    loc, rot = pose_of(player)
    assert loc.x == pytest.approx(3.0)  # LIVE pose, not the buffer midpoint


def test_player_is_interpolated_when_ai_owned():
    from engine.host_loop import _make_render_pose_provider
    player = _FakeShip((3.0, 0.0, 0.0))
    buf = _buffer_with(1, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    session = _FakeSession({player: 1})

    pose_of = _make_render_pose_provider(
        session, buf, 0.5, interpolate_player=True, player_iid=1)
    loc, rot = pose_of(player)
    assert loc.x == pytest.approx(5.0)  # interpolated midpoint, not live 3.0


def test_unknown_object_falls_back_to_live():
    from engine.host_loop import _make_render_pose_provider
    stray = _FakeShip((2.0, 4.0, 6.0))
    buf = _buffer_with(1, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    session = _FakeSession({})  # stray not in the mapping

    pose_of = _make_render_pose_provider(
        session, buf, 0.5, interpolate_player=True, player_iid=1)
    loc, rot = pose_of(stray)
    assert (loc.x, loc.y, loc.z) == pytest.approx((2.0, 4.0, 6.0))
