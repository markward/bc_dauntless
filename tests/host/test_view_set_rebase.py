"""A hand-off changes the VIEWED set, and with it every view coordinate
(in-system-warp spec §3; system-frames spec §5).

When the player is handed off from Ona1 to Ona2 the camera's point of view is
unchanged in the system, but view coordinates jump by the anchor difference
(~100k GU). Two things remember last frame's view coordinates and must not
read that jump as motion:

* the chase / tracking cameras' lagged eye (ChaseCamera._advance_eye_lag):
  left in the old set's coordinates it is clamped to MAX_LAG_RADII x radius
  off the new ideal -- a visible one-frame jump, then a swing back;
* the dust pass's eye travel (dust_pass.cc, render_origin::eye_travel): the
  world eye moves ~100k GU in one frame -> 600 GU streaks at the drop-out.

The host re-bases the cameras by the offset and drops the dust (and
volumetric-nebula / motion-blur) history through the existing native
reset_render_origin, which exists for exactly this kind of discontinuity.
What these tests cannot show is the frame itself -- that is live-only.
"""
import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.cameras.chase import _ChaseCamera as ChaseCamera
from engine.cameras.director import _CameraDirector


def _settled_chase(loc):
    c = ChaseCamera()
    c.set_ship_radius(1.0)
    for _ in range(600):                     # 10 s: the lag has settled
        eye, _, _ = c.compute_camera(loc, TGMatrix3(), dt=1.0 / 60.0)
    return c, eye


def test_a_rebased_chase_camera_does_not_jump():
    off = (-100000.0, 250.0, -30.0)
    c, eye0 = _settled_chase(TGPoint3(0.0, 0.0, 0.0))
    c.rebase(off)
    eye1, _, _ = c.compute_camera(TGPoint3(*off), TGMatrix3(), dt=1.0 / 60.0)
    assert eye1 == pytest.approx(tuple(eye0[i] + off[i] for i in range(3)),
                                 abs=1e-6)


def test_an_unrebased_chase_camera_would_jump():
    """The bug, pinned: without the rebase the new frame's eye is clamped to
    MAX_LAG_RADII radii off where it belongs."""
    off = (-100000.0, 250.0, -30.0)
    c, eye0 = _settled_chase(TGPoint3(0.0, 0.0, 0.0))
    eye1, _, _ = c.compute_camera(TGPoint3(*off), TGMatrix3(), dt=1.0 / 60.0)
    want = tuple(eye0[i] + off[i] for i in range(3))
    d = sum((eye1[i] - want[i]) ** 2 for i in range(3)) ** 0.5
    assert d == pytest.approx(ChaseCamera.MAX_LAG_RADII * 1.0, rel=1e-3)


def test_rebase_before_the_first_frame_is_a_no_op():
    c = ChaseCamera()
    c.rebase((1.0, 2.0, 3.0))
    assert c._smoothed_eye is None


def test_the_director_rebases_both_cameras_and_the_ghost():
    d = _CameraDirector()
    d.chase._smoothed_eye = (1.0, 2.0, 3.0)
    d.tracking._smoothed_eye = [4.0, 5.0, 6.0]
    from engine.cameras.director import _GhostTarget
    d._ghost = _GhostTarget(TGPoint3(7.0, 8.0, 9.0), TGMatrix3(), 1.0)
    d._ghost_aim = TGPoint3(10.0, 11.0, 12.0)
    d.rebase((100.0, 0.0, -1.0))
    assert d.chase._smoothed_eye == (101.0, 2.0, 2.0)
    assert list(d.tracking._smoothed_eye) == [104.0, 5.0, 5.0]
    g = d._ghost.GetWorldLocation()
    assert (g.x, g.y, g.z) == (107.0, 8.0, 8.0)
    a = d._ghost_aim
    assert (a.x, a.y, a.z) == (110.0, 11.0, 11.0)


# ── the host: detect a viewed-set change and re-base ───────────────────────

@pytest.fixture
def ona():
    import App
    from tests.helpers.fresh_world import _fresh_world
    from tests.helpers.mapped_regions import load_region
    _fresh_world()
    a, b = load_region("Ona", "Ona1"), load_region("Ona", "Ona2")
    yield a, b
    App.g_kSetManager._sets.clear()


def test_the_view_offset_is_the_anchor_difference(ona):
    from engine.host_loop import _view_rebase_offset
    from engine.systems import frames
    a, b = ona
    off = _view_rebase_offset(a, b)
    assert off == frames.offset_between(b, a)
    assert max(abs(c) for c in off) > 1000.0, "premise: distinct anchors"


def test_no_view_offset_without_a_change(ona):
    from engine.host_loop import _view_rebase_offset
    a, _ = ona
    assert _view_rebase_offset(a, a) is None
    assert _view_rebase_offset(None, a) is None
    assert _view_rebase_offset(a, None) is None


class _FakeRenderer:
    def __init__(self):
        self.calls = []

    def reset_render_origin(self):
        self.calls.append("reset_render_origin")


def test_a_view_rebase_shifts_the_cameras_and_drops_the_dust_history():
    from engine.host_loop import _rebase_view
    from engine.systems import frames
    r = _FakeRenderer()
    d = _CameraDirector()
    d.chase._smoothed_eye = (1.0, 2.0, 3.0)
    frames.set_render_origin((5.0, 5.0, 5.0))
    try:
        _rebase_view(r, d, (10.0, 0.0, 0.0))
        assert d.chase._smoothed_eye == (11.0, 2.0, 3.0)
        assert r.calls == ["reset_render_origin"]
        assert frames.render_origin() == (0.0, 0.0, 0.0)
    finally:
        frames.reset_render_origin()


def test_the_host_loop_rebases_the_view_before_it_solves_the_camera():
    import inspect
    from engine import host_loop
    from tests.helpers.source_guards import code_only
    src = code_only(inspect.getsource(host_loop.run))
    i_rebase = src.index("_rebase_view(")
    assert i_rebase < src.index("_compute_camera(")
    assert i_rebase < src.index("_apply_render_origin(")
