"""The player's drawn pose during an in-system dash (in-system-warp spec §4).

A dash moves the player on the 60 Hz sim tick (its WarpFlight), not per
render frame the way _PlayerControl flies it, so -- like a helm-AI order or
a cutscene -- it must be render-interpolated or it judders above 60 Hz. And a
hand-off moves the player into another region set, whose coordinates differ
by the anchor difference (~100k GU): the player's interpolation slot and any
handover-smoothing window hold poses from the OLD set, so the one frame that
blends old and new would draw the ship between the two. The host re-seeds the
slot and drops the window when the player's set changes.
"""
import pytest

from engine import host_io
from engine.appc.math import TGMatrix3, TGPoint3
from engine.core.native_transform_buffer import NativeTransformBuffer
from engine.host_loop import (_player_render_interpolated,
                              _rebase_player_render)
from tests.helpers import host_frame_source


class _FakePlayer:
    def __init__(self, loc=(0.0, 0.0, 0.0), ai=None):
        self._loc = TGPoint3(*loc)
        self._rot = TGMatrix3()
        self._ai = ai

    def GetAI(self):
        return self._ai

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


# ── interpolation policy ───────────────────────────────────────────────────

def test_a_manually_flown_player_is_drawn_live():
    assert _player_render_interpolated(
        _FakePlayer(), sim_frozen=False, cutscene_active=False) is False


def test_a_dashing_player_is_interpolated():
    p = _FakePlayer()
    p.__dict__["_dash"] = object()          # engine.appc.dash's own state slot
    assert _player_render_interpolated(
        p, sim_frozen=False, cutscene_active=False) is True


def test_an_ai_owned_or_scripted_player_is_still_interpolated():
    assert _player_render_interpolated(
        _FakePlayer(ai=object()), sim_frozen=False, cutscene_active=False)
    assert _player_render_interpolated(
        _FakePlayer(), sim_frozen=False, cutscene_active=True)
    assert not _player_render_interpolated(
        _FakePlayer(), sim_frozen=True, cutscene_active=True)


def test_no_player_is_not_interpolated():
    assert _player_render_interpolated(
        None, sim_frozen=False, cutscene_active=True) is False


# ── a hand-off never blends set A's pose with set B's ──────────────────────

@pytest.fixture
def native_player():
    """A store-backed player with a model-0 render instance, tracked and
    composed by the native buffer."""
    h = pytest.importorskip("_dauntless_host")
    from engine.appc.objects import ObjectClass
    o = ObjectClass()
    iid = h.create_instance(0)
    h.set_instance_sim_source(iid, *o._xform, 1.0, (0.0, 0.0, 0.0))
    buf = NativeTransformBuffer()
    buf.track(iid, compose=True)
    try:
        yield o, iid, buf
    finally:
        h.interp_handover_cancel()
        h.destroy_instance(iid)


def test_a_hand_off_reseeds_the_players_slot_at_its_new_pose(native_player):
    o, iid, buf = native_player
    o.SetTranslateXYZ(0.0, 0.0, 0.0)                             # set A
    buf.capture()
    buf.roll()
    o.SetTranslateXYZ(-100000.0, 5.0, 0.0)                       # set B coords
    buf.capture()
    _rebase_player_render(buf, iid)
    loc, _ = buf.sample(iid, 0.5)
    assert (loc.x, loc.y, loc.z) == pytest.approx((-100000.0, 5.0, 0.0))


def test_a_hand_off_drops_a_handover_window_from_the_old_set(native_player):
    _o, iid, buf = native_player
    host_io.interp_compose(0.0)
    host_io.interp_handover_begin(iid)
    assert host_io.interp_handover_active()
    _rebase_player_render(buf, None)
    assert not host_io.interp_handover_active()


# ── the host loop wires both, in order ─────────────────────────────────────

def test_the_host_loop_rebases_before_it_opens_a_handover_window():
    """The rebase must null last frame's drawn pose BEFORE
    _drive_handover_smoother reads it, or the flip at the drop-out (dash
    ends -> live) opens a window from the old set's pose."""
    from engine import host_loop
    from tests.helpers.source_guards import code_only
    src = code_only(host_frame_source.run_source())
    i_interp = src.index("_player_render_interpolated(")
    i_rebase = src.index("_rebase_player_render(")
    i_drive = src.index("_drive_handover_smoother(")
    assert i_interp < i_rebase < i_drive
