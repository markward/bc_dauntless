"""The player's drawn pose stays continuous across a helm handover.

The player renders live while manually flown and interpolated while an AI or
script drives it, and those two pipelines sit a tick apart. Without smoothing,
the frame where the pipeline flips jumps by that phase offset. These tests pin
the two host-loop pieces that remove it: the transition detector that opens a
smoothing window, and the pose provider that applies it to BOTH the camera and
the renderer (they share `pose_of`, so they cannot disagree).
"""
import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.handover_smoother import HandoverSmoother, SMOOTH_DURATION_S
from engine.core.transform_buffer import TransformBuffer
from engine.host_loop import _drive_handover_smoother, _make_render_pose_provider


class _FakeShip:
    """Mirrors the surface pose_of actually uses: the two world accessors."""

    def __init__(self, loc, rot=None):
        self._loc = loc
        self._rot = rot if rot is not None else TGMatrix3()

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot

    def set_live(self, loc):
        self._loc = loc


class _FakeSession:
    def __init__(self, ship, iid):
        self.ship_instances = {ship: iid}


def _pt(x, y, z):
    return TGPoint3(float(x), float(y), float(z))


def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5


def test_no_smoothing_starts_when_the_pipeline_does_not_flip():
    s = HandoverSmoother()
    _drive_handover_smoother(s, prev_interp=True, cur_interp=True,
                             prev_drawn=(_pt(1, 0, 0), TGMatrix3()))
    assert not s.active


def test_smoothing_starts_when_the_pipeline_flips():
    s = HandoverSmoother()
    _drive_handover_smoother(s, prev_interp=True, cur_interp=False,
                             prev_drawn=(_pt(1, 0, 0), TGMatrix3()))
    assert s.active


def test_smoothing_starts_in_the_other_direction_too():
    """Manual -> AI lurches as well, not only AI -> manual."""
    s = HandoverSmoother()
    _drive_handover_smoother(s, prev_interp=False, cur_interp=True,
                             prev_drawn=(_pt(1, 0, 0), TGMatrix3()))
    assert s.active


def test_first_frame_does_not_start_smoothing():
    """No previous frame means nothing was on screen to blend from."""
    s = HandoverSmoother()
    _drive_handover_smoother(s, prev_interp=None, cur_interp=False,
                             prev_drawn=None)
    assert not s.active


def test_pose_provider_applies_the_smoother_to_the_player():
    ship = _FakeShip(_pt(100.0, 0.0, 0.0))
    session = _FakeSession(ship, iid=7)
    smoother = HandoverSmoother()
    smoother.begin(_pt(0.0, 0.0, 0.0), TGMatrix3())

    pose_of = _make_render_pose_provider(
        session, TransformBuffer(), 0.0,
        interpolate_player=False, player_iid=7, smoother=smoother)

    loc, _rot = pose_of(ship)
    assert loc.x == 0.0, "at t=0 the drawn pose must be the frozen one"


def test_pose_provider_leaves_other_ships_alone():
    """The smoother is player-only; another ship must not be dragged toward
    the player's frozen pose."""
    player = _FakeShip(_pt(100.0, 0.0, 0.0))
    other = _FakeShip(_pt(50.0, 0.0, 0.0))
    session = _FakeSession(player, iid=7)
    session.ship_instances[other] = 9
    smoother = HandoverSmoother()
    smoother.begin(_pt(0.0, 0.0, 0.0), TGMatrix3())

    pose_of = _make_render_pose_provider(
        session, TransformBuffer(), 0.0,
        interpolate_player=False, player_iid=7, smoother=smoother)

    loc, _rot = pose_of(other)
    assert loc.x == 50.0


def test_drawn_pose_is_continuous_across_a_handover():
    """The regression this whole change exists for.

    Frame A: AI-driven, drawn interpolated one tick behind live.
    Frame B: manual, drawn live. Without the smoother the drawn pose jumps by
    the phase offset; with it, frame B must continue from frame A.
    """
    iid = 7
    ship = _FakeShip(_pt(10.0, 0.0, 0.0))
    session = _FakeSession(ship, iid)
    buf = TransformBuffer()
    # prev tick at x=9, current tick at x=10 -> interpolated draw sits behind.
    buf.set_current(iid, _pt(9.0, 0.0, 0.0), TGMatrix3())
    buf.roll()
    buf.set_current(iid, _pt(10.0, 0.0, 0.0), TGMatrix3())
    smoother = HandoverSmoother()

    # --- Frame A: AI owns the helm, pose is interpolated.
    pose_a = _make_render_pose_provider(
        session, buf, 0.0, interpolate_player=True, player_iid=iid,
        smoother=smoother)
    drawn_a, rot_a = pose_a(ship)
    assert drawn_a.x == 9.0, "interpolated draw should trail the live pose"

    # --- Frame B: player takes the helm back. Live pose has advanced.
    ship.set_live(_pt(10.5, 0.0, 0.0))
    _drive_handover_smoother(smoother, prev_interp=True, cur_interp=False,
                             prev_drawn=(drawn_a, rot_a))
    pose_b = _make_render_pose_provider(
        session, buf, 0.0, interpolate_player=False, player_iid=iid,
        smoother=smoother)
    drawn_b, _ = pose_b(ship)

    jump = _dist(drawn_a, drawn_b)
    assert jump < 1e-9, (
        "drawn pose jumped %.4f GU across the handover; the smoothing window "
        "must start from the pose that was on screen" % jump)


def test_the_ship_reaches_its_true_pose_after_the_window():
    """Smoothing must be transient — the ship ends up where it really is, not
    permanently offset."""
    iid = 7
    ship = _FakeShip(_pt(10.0, 0.0, 0.0))
    session = _FakeSession(ship, iid)
    smoother = HandoverSmoother()
    smoother.begin(_pt(0.0, 0.0, 0.0), TGMatrix3())
    smoother.advance(SMOOTH_DURATION_S)

    pose_of = _make_render_pose_provider(
        session, TransformBuffer(), 0.0,
        interpolate_player=False, player_iid=iid, smoother=smoother)

    loc, _rot = pose_of(ship)
    assert (loc.x, loc.y, loc.z) == (10.0, 0.0, 0.0)


def test_pose_provider_without_a_smoother_is_unchanged():
    """The smoother argument is optional; omitting it must behave exactly as
    before, so every existing caller and test keeps its meaning."""
    ship = _FakeShip(_pt(3.0, 4.0, 5.0))
    session = _FakeSession(ship, iid=7)
    pose_of = _make_render_pose_provider(
        session, TransformBuffer(), 0.0,
        interpolate_player=False, player_iid=7)
    loc, _rot = pose_of(ship)
    assert (loc.x, loc.y, loc.z) == (3.0, 4.0, 5.0)
