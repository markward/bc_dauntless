"""The player's drawn pose stays continuous across a helm handover.

The player renders live while manually flown and interpolated while an AI or
script drives it, and those two pipelines sit a tick apart. Without smoothing,
the frame where the pipeline flips jumps by that phase offset. These tests pin
the two host-loop pieces that remove it, through the real native buffer
(phase 3c): the transition detector that opens the native handover window
from the pose the compose last drew, and the pose provider whose sample (the
camera) is the pose the compose draws (the hull), blend included.
"""
import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine import host_io  # noqa: E402
from engine.appc.objects import ObjectClass  # noqa: E402
from engine.core.handover_smoother import SMOOTH_DURATION_S  # noqa: E402
from engine.core.native_transform_buffer import NativeTransformBuffer  # noqa: E402,E501
from engine.host_loop import (_drive_handover_smoother,  # noqa: E402
                              _make_render_pose_provider)


class _FakeSession:
    def __init__(self):
        self.ship_instances = {}


@pytest.fixture
def scene():
    """(session, buf, make): make(x) -> (obj, iid), a store-backed object at
    x with a model-0 render instance, tracked + composed."""
    session, buf, made = _FakeSession(), NativeTransformBuffer(), []

    def _make(x):
        o = ObjectClass()
        o.SetTranslateXYZ(x, 0.0, 0.0)
        iid = _h.create_instance(0)
        made.append(iid)
        _h.set_instance_sim_source(iid, *o._xform, 1.0, (0.0, 0.0, 0.0))
        buf.track(iid, compose=True)
        session.ship_instances[o] = iid
        return o, iid
    yield session, buf, _make
    _h.interp_handover_cancel()
    for iid in made:
        _h.destroy_instance(iid)


def _x(pose):
    return pose[0].x


def test_no_smoothing_starts_when_the_pipeline_does_not_flip(scene):
    _session, _buf, make = scene
    _o, iid = make(1.0)
    host_io.interp_compose(0.0)
    _drive_handover_smoother(iid, prev_interp=True, cur_interp=True,
                             prev_drawn=object())
    assert not host_io.interp_handover_active()


@pytest.mark.parametrize("prev, cur", [(True, False), (False, True)])
def test_smoothing_starts_when_the_pipeline_flips_either_way(scene, prev, cur):
    """Manual -> AI lurches as well, not only AI -> manual."""
    _session, _buf, make = scene
    _o, iid = make(1.0)
    host_io.interp_compose(0.0)
    _drive_handover_smoother(iid, prev_interp=prev, cur_interp=cur,
                             prev_drawn=object())
    assert host_io.interp_handover_active()


def test_first_frame_does_not_start_smoothing(scene):
    """No previous frame means nothing was on screen to blend from."""
    _session, _buf, make = scene
    _o, iid = make(1.0)
    host_io.interp_compose(0.0)
    _drive_handover_smoother(iid, prev_interp=None, cur_interp=False,
                             prev_drawn=None)
    assert not host_io.interp_handover_active()


def test_the_blend_is_in_the_players_sample_and_leaves_others_alone(scene):
    session, buf, make = scene
    player, pid = make(0.0)
    other, _oid = make(50.0)
    host_io.interp_set_live(pid, True)
    host_io.interp_compose(0.0)                 # on screen: x = 0
    player.SetTranslateXYZ(100.0, 0.0, 0.0)
    buf.capture()
    other.SetTranslateXYZ(60.0, 0.0, 0.0)
    _drive_handover_smoother(pid, prev_interp=False, cur_interp=True,
                             prev_drawn=object())
    pose_of = _make_render_pose_provider(session, buf, 1.0)
    assert _x(pose_of(player)) == pytest.approx(0.0), (
        "at t=0 the drawn pose must be the frozen one")
    buf.capture()
    assert _x(pose_of(other)) == pytest.approx(60.0)


def test_drawn_pose_is_continuous_across_a_handover(scene):
    """The regression this whole change exists for.

    Frame A: AI-driven, drawn interpolated one tick behind live.
    Frame B: manual, drawn live. Without the blend the drawn pose jumps by
    the phase offset; with it, frame B must continue from frame A.
    """
    session, buf, make = scene
    ship, iid = make(9.0)
    buf.roll()
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    buf.capture()

    # --- Frame A: AI owns the helm, pose is interpolated.
    pose_a = _make_render_pose_provider(session, buf, 0.0)(ship)
    host_io.interp_compose(0.0)
    assert _x(pose_a) == pytest.approx(9.0), (
        "interpolated draw should trail the live pose")

    # --- Frame B: player takes the helm back. Live pose has advanced.
    ship.SetTranslateXYZ(10.5, 0.0, 0.0)
    buf.capture()
    host_io.interp_set_live(iid, True)
    _drive_handover_smoother(iid, prev_interp=True, cur_interp=False,
                             prev_drawn=pose_a)
    pose_b = _make_render_pose_provider(session, buf, 0.0)(ship)
    host_io.interp_compose(0.0)
    jump = abs(_x(pose_b) - _x(pose_a))
    assert jump < 1e-9, (
        "drawn pose jumped %.4f GU across the handover; the smoothing window "
        "must start from the pose that was on screen" % jump)
    assert _h.instance_translation(iid, drawn=True)[0] == pytest.approx(
        _x(pose_b), abs=1e-12), "camera and hull agree"


def test_the_ship_reaches_its_true_pose_after_the_window(scene):
    """Smoothing must be transient — the ship ends up where it really is, not
    permanently offset."""
    session, buf, make = scene
    ship, iid = make(0.0)
    host_io.interp_set_live(iid, True)
    host_io.interp_compose(0.0)
    host_io.interp_set_live(iid, False)
    _drive_handover_smoother(iid, prev_interp=False, cur_interp=True,
                             prev_drawn=object())
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    buf.capture()
    buf.roll()
    buf.capture()
    host_io.interp_handover_advance(SMOOTH_DURATION_S)
    assert not host_io.interp_handover_active()
    loc, _rot = _make_render_pose_provider(session, buf, 0.0)(ship)
    assert (loc.x, loc.y, loc.z) == pytest.approx((10.0, 0.0, 0.0))
