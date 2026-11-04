"""The host loop draws every ship through the native interpolation buffer
(native motion phase 3c, host loop).

No Python render path remains: `_sync_instance_transforms` tracks each ship's
render instance in the native buffer (`interp_track(iid, True, True)`, once),
pushes no matrix and binds no ship to the store, then draws them all with ONE
`interp_compose(alpha)` after the ship loop. The player is composed too, live
(`interp_set_live`) while manually flown and interpolated otherwise, and its
helm-handover blend is native, so the camera (`pose_of` -> `interp_sample`)
and the hull (`interp_compose`) read one drawn pose.

The first tests stub the host_io seam and record the calls in order; the
`*_native` ones run the real bindings (skipped without `_dauntless_host`).
"""
import re

import pytest

from engine import host_io, host_loop
from engine.core.native_transform_buffer import NativeTransformBuffer
from engine.core.transform_buffer import advance_ticks
from tests.helpers.source_guards import code_only
from tests.unit.test_render_transform_binding import _FakeRenderer, _Obj
from tests.helpers import host_frame_source

_RECORDED = ("interp_track", "interp_roll", "interp_reseat", "interp_capture",
             "interp_snap", "interp_reset_all", "interp_set_live",
             "interp_handover_begin", "interp_handover_advance",
             "interp_handover_cancel", "interp_compose", "interp_sample")


@pytest.fixture
def native(monkeypatch):
    """Stub every interp_* wrapper and the sim-source / store-binding seams;
    record each call, in order, as (name, *args)."""
    log = []

    def _rec(name, ret=None):
        def _f(*a):
            log.append((name,) + a)
            return ret
        return _f
    for name in _RECORDED:
        monkeypatch.setattr(host_io, name, _rec(name), raising=False)
    monkeypatch.setattr(host_io, "interp_handover_active", lambda: False,
                        raising=False)
    monkeypatch.setattr(
        host_io, "set_instance_sim_source",
        lambda iid, i, g, s, o: log.append(("sim_source", iid, i, g)) or True)
    monkeypatch.setattr(
        host_io, "set_instance_transform_slot",
        lambda *a: log.append(("bind",) + a) or True)
    return log


def _scene():
    player, other = _Obj(), _Obj(x=40.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player
    return session, player, other


def _sync(r, session, player, buf, alpha=0.5, **kw):
    host_loop._sync_instance_transforms(
        r, session, player, buf, alpha, game_time=1.0, model_scale=2.0, **kw)


def _named(log, name, iid=None):
    return [e for e in log if e[0] == name and (iid is None or e[1] == iid)]


def test_non_player_ships_are_tracked_and_composed_never_pushed(native):
    r = _FakeRenderer()
    session, player, _other = _scene()
    buf = NativeTransformBuffer()
    for _ in range(3):
        _sync(r, session, player, buf)
    assert r.pushed == []
    assert _named(native, "interp_track", 2) == [("interp_track", 2, True, True)]
    assert buf.has(2)


def test_compose_runs_once_after_the_ship_loop_with_this_frames_alpha(native):
    r = _FakeRenderer()
    session, player, _other = _scene()
    _sync(r, session, player, NativeTransformBuffer(), alpha=0.3)
    names = [e[0] for e in native]
    assert names.count("interp_compose") == 1
    i = names.index("interp_compose")
    assert native[i] == ("interp_compose", 0.3)
    assert "interp_track" in names[:i] and "sim_source" in names[:i]
    assert not {"interp_track", "sim_source"} & set(names[i + 1:]), (
        "compose must run after every ship is tracked and sourced")


def test_player_is_composed_natively_in_both_modes(native):
    r = _FakeRenderer()
    session, player, _other = _scene()
    buf = NativeTransformBuffer()
    for interp in (False, True, False):
        _sync(r, session, player, buf, player_is_interpolated=interp)
    assert r.pushed == []
    assert _named(native, "bind") == [], "no ship is bound to the store"
    assert _named(native, "interp_track", 1) == [("interp_track", 1, True, True)]
    assert _named(native, "interp_set_live", 1) == [
        ("interp_set_live", 1, True), ("interp_set_live", 1, False),
        ("interp_set_live", 1, True)]


def test_a_former_player_is_drawn_interpolated(native):
    """RecreatePlayer / SetPlayer: the ship that was flown live becomes an
    ordinary interpolated ship."""
    r = _FakeRenderer()
    session, player, other = _scene()
    buf = NativeTransformBuffer()
    _sync(r, session, player, buf, player_is_interpolated=False)
    session.player = other
    _sync(r, session, other, buf, player_is_interpolated=False)
    assert _named(native, "interp_set_live", 1) == [
        ("interp_set_live", 1, True), ("interp_set_live", 1, False)]
    assert _named(native, "interp_set_live", 2) == [
        ("interp_set_live", 2, True)]


def test_a_changed_sim_source_snaps_the_tracked_slot(native):
    """Snapshots are keyed by iid: a new store slot under the same iid must
    never blend across the two objects' poses."""
    r = _FakeRenderer()
    session, player, other = _scene()
    buf = NativeTransformBuffer()
    _sync(r, session, player, buf)
    assert _named(native, "interp_snap") == [], "a first source never snaps"
    other._xform = (8, 3)
    del native[:]
    _sync(r, session, player, buf)
    names = [e[:2] for e in native]
    assert ("interp_snap", 2) in names
    assert names.index(("sim_source", 2)) < names.index(("interp_snap", 2))
    assert ("interp_snap", 1) not in names, "an unchanged source never snaps"


def test_prune_untracks_a_dropped_ship(native):
    r = _FakeRenderer()
    session, player, other = _scene()
    buf = NativeTransformBuffer()
    _sync(r, session, player, buf)
    del session.ship_instances[other]
    _sync(r, session, player, buf)
    assert ("interp_track", 2, False, False) in native
    assert not buf.has(2)
    assert 2 not in session.interp_modes


def _run_src():
    return code_only(host_frame_source.run_source())


def test_capture_runs_before_the_camera_pose_is_resolved():
    src = _run_src()
    i_capture = src.index("_xform_buf.capture()")
    i_pose = src.index("_pose_of(player)")
    assert i_capture < i_pose


def test_handover_advances_once_before_the_camera_sample_and_compose():
    """The camera's interp_sample and the sync's interp_compose must see the
    SAME handover elapsed time: one advance a frame, ahead of both."""
    src = _run_src()
    assert src.count("interp_handover_advance(") == 1
    i_adv = src.index("interp_handover_advance(_player_dt)")
    i_drive = src.index("_drive_handover_smoother(")
    i_pose = src.index("_pose_of(player)")
    i_sync = src.index("_sync_instance_transforms(")
    assert src.index("_xform_buf.capture()") < i_adv < i_drive < i_pose < i_sync


def test_no_python_render_path_is_left_in_run():
    src = _run_src()
    for gone in (r"\bTransformBuffer\(", r"HandoverSmoother\(",
                 r"_interp_live_poses", r"set_current\("):
        assert not re.search(gone, src), gone
    assert "NativeTransformBuffer()" in src


def test_player_hand_off_snaps_native_slot(native):
    host_loop._rebase_player_render(NativeTransformBuffer(), 7)
    assert ("interp_handover_cancel",) in native
    assert ("interp_snap", 7) in native


def test_reset_all_reseeds_without_smear(native):
    NativeTransformBuffer().reset_all()
    assert native == [("interp_reset_all",)]
    src = _run_src()
    for owner, call in (("def _snap_scene(", "_xform_buf.reset_all()"),
                        ("def _on_player_change(", "_xb.reset_all()")):
        i = src.index(owner)
        body = src[i:src.index(call, i)]
        assert body.count("def ") == 1, "%s must call %s" % (owner, call)


def test_drive_handover_begins_natively_only_on_a_flip(native):
    drawn = object()
    host_loop._drive_handover_smoother(7, True, True, drawn)
    host_loop._drive_handover_smoother(7, None, False, drawn)
    host_loop._drive_handover_smoother(7, True, False, None)
    assert _named(native, "interp_handover_begin") == []
    host_loop._drive_handover_smoother(7, True, False, drawn)
    host_loop._drive_handover_smoother(7, False, True, drawn)
    assert _named(native, "interp_handover_begin") == [
        ("interp_handover_begin", 7), ("interp_handover_begin", 7)]


# ── the real bindings ──────────────────────────────────────────────────────

def _h():
    return pytest.importorskip("_dauntless_host")


@pytest.fixture
def real_ship():
    """A model-0 render instance for a store-backed ObjectClass."""
    h = _h()
    from engine.appc.objects import ObjectClass
    o = ObjectClass()
    o.SetTranslateXYZ(0.0, 0.0, 0.0)
    iid = h.create_instance(0)
    try:
        yield h, o, iid
    finally:
        h.interp_handover_cancel()
        h.destroy_instance(iid)


def test_pose_of_player_equals_the_composed_pose_native(real_ship):
    """Camera and hull agree every frame, through a live -> interpolated
    handover window too, in run()'s order: roll/ticks, capture, advance,
    begin on a flip, the camera's sample, then the sync's compose."""
    h, o, iid = real_ship
    session = host_loop.MissionSession("t")
    session.ship_instances[o] = iid
    session.player = o
    buf = NativeTransformBuffer()
    r = _FakeRenderer()
    prev_interp, prev_drawn, x, blended = None, None, 0.0, 0
    for frame in range(30):
        interp = frame >= 10              # an AI takes the helm at frame 10
        x_box = [x]

        def tick():
            x_box[0] += 0.1
            o.SetTranslateXYZ(x_box[0], 0.0, 0.0)
        advance_ticks(buf, 1, tick)
        x = x_box[0]
        host_loop._set_interp_mode(session, buf, iid, not interp)
        buf.capture()
        host_io.interp_handover_advance(0.02)
        host_loop._drive_handover_smoother(iid, prev_interp, interp,
                                           prev_drawn)
        pose_of = host_loop._make_render_pose_provider(session, buf, 0.25)
        loc, _rot = pose_of(o)
        _sync(r, session, o, buf, alpha=0.25, player_is_interpolated=interp)
        drawn = h.instance_translation(iid, drawn=True)
        assert drawn == pytest.approx((loc.x, loc.y, loc.z), abs=1e-9), frame
        if h.interp_handover_active():
            blended += 1
        prev_interp, prev_drawn = interp, (loc, _rot)
    assert r.pushed == []
    assert blended >= 5, "premise: the handover window was open"


def test_drawn_motion_is_even_across_mixed_tick_frames_native(real_ship):
    """The native twin of test_transform_buffer's undock pattern: 2,1,1,1
    ticks per frame at 20 ms through advance_ticks + the frame-end capture."""
    h, o, iid = real_ship
    from engine.core.timestep import step_accumulator
    h.set_instance_sim_source(iid, *o._xform, 1.0, (0.0, 0.0, 0.0))
    buf = NativeTransformBuffer()
    buf.track(iid, compose=True)
    tick_dt, frame_dt = 1.0 / 60.0, 0.020
    state = {"x": 0.0}

    def tick():
        state["x"] += 1.0
        o.SetTranslateXYZ(state["x"], 0.0, 0.0)
    acc, drawn = 0.0, []
    for _ in range(40):
        acc, n = step_accumulator(acc, frame_dt, tick_dt, 0.25)
        advance_ticks(buf, n, tick)
        buf.capture()
        if state["x"]:
            drawn.append(buf.sample(iid, acc / tick_dt)[0].x)
    steps = [b - a for a, b in zip(drawn[5:], drawn[6:])]
    assert max(steps) - min(steps) < 1e-9, steps
