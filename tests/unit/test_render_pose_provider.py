"""The render-pose provider feeds the camera the SAME per-ship pose the
renderer draws (smooth-motion fix).

Every ship the native buffer tracks, the player included, is read from its
`sample`: the drawn pose `interp_compose` draws (the lerp for a ship on the
60 Hz tick, the live store pose for the manually flown player, then the
player's handover blend; pinned natively by
tests/host/test_native_interp_bindings.py and
tests/host/test_handover_continuity.py). Anything untracked, or tracked with
nothing to draw, falls back to its live pose. A recording double stands in
for NativeTransformBuffer here.
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


class _Buf:
    """NativeTransformBuffer's has/sample surface, recording each sample."""

    def __init__(self, poses):
        self.poses = poses          # iid -> (loc, rot) | None
        self.sampled = []

    def has(self, iid):
        return iid in self.poses

    def sample(self, iid, alpha):
        self.sampled.append((iid, alpha))
        return self.poses[iid]


def _pose(x):
    from engine.appc.math import TGPoint3, TGMatrix3
    return TGPoint3(x, 0.0, 0.0), TGMatrix3()


def test_a_tracked_ship_reads_the_native_drawn_pose():
    from engine.host_loop import _make_render_pose_provider
    ship = _FakeShip((0.0, 0.0, 0.0))
    buf = _Buf({7: _pose(5.0)})
    pose_of = _make_render_pose_provider(_FakeSession({ship: 7}), buf, 0.5)
    loc, _rot = pose_of(ship)
    assert loc.x == pytest.approx(5.0)
    assert buf.sampled == [(7, 0.5)]


def test_the_player_reads_the_same_sample_as_any_ship():
    """No player special case left in Python: its live mode and handover
    blend are already in the native sample."""
    from engine.host_loop import _make_render_pose_provider
    player = _FakeShip((3.0, 0.0, 0.0))
    buf = _Buf({1: _pose(9.0)})
    pose_of = _make_render_pose_provider(_FakeSession({player: 1}), buf, 0.25)
    assert pose_of(player)[0].x == pytest.approx(9.0)


def test_tracked_with_nothing_to_draw_falls_back_to_live():
    from engine.host_loop import _make_render_pose_provider
    ship = _FakeShip((2.0, 4.0, 6.0))
    buf = _Buf({7: None})
    pose_of = _make_render_pose_provider(_FakeSession({ship: 7}), buf, 0.5)
    loc, _rot = pose_of(ship)
    assert (loc.x, loc.y, loc.z) == pytest.approx((2.0, 4.0, 6.0))


def test_unknown_object_falls_back_to_live_without_sampling():
    from engine.host_loop import _make_render_pose_provider
    stray = _FakeShip((2.0, 4.0, 6.0))
    untracked = _FakeShip((1.0, 1.0, 1.0))
    buf = _Buf({1: _pose(10.0)})
    pose_of = _make_render_pose_provider(
        _FakeSession({untracked: 3}), buf, 0.5)
    loc, _rot = pose_of(stray)
    assert (loc.x, loc.y, loc.z) == pytest.approx((2.0, 4.0, 6.0))
    loc, _rot = pose_of(untracked)
    assert (loc.x, loc.y, loc.z) == pytest.approx((1.0, 1.0, 1.0))
    assert buf.sampled == []
