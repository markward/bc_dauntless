"""Regression: AT_MOVE completion must NOT be gated on bridge view.

A CharacterAction AT_MOVE defers completion — the walk controller fires the
action's Completed() when the walk clip settles, and Completed() advances the
mission TGSequence. E1M1's UndockCutscene chains Picard's ``AT_MOVE "P"``
(walk-to-chair) -> Inspection (enables the crew menus) -> collision re-enable,
and that walk fires right after an EXTERIOR drydock cutscene, so the active view
is not the bridge when the AT_MOVE runs.

Before this fix the host loop pumped ``walk_ctrl.update()`` only inside
``if view_mode.is_bridge:`` (a block otherwise full of purely-visual bridge
pumps). The undock walk was therefore never pumped -> never settled ->
Completed() never fired -> the sequence jammed before Inspection: crew menus
never enabled and control never restored (freelook + F1-F5 all dead). The
intro walk-on happens in bridge view, so it never hit this.

``_pump_walk_controller`` is the view-independent seam that runs every unpaused
frame regardless of view. These tests drive an AT_MOVE to completion through
that seam alone — with no bridge view anywhere — proving the walk can no longer
hang the mission sequence.
"""
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_walk as bcw
from engine.bridge_character_walk import BridgeCharacterWalkController
from engine.host_loop import _pump_walk_controller


class _FakeRenderer:
    def __init__(self):
        self.walked = []

    def load_instance_clip(self, iid, path):
        return 200

    def play_instance_walk(self, iid, ci):
        self.walked.append((iid, ci))

    def set_instance_rest_pose(self, iid, ci, at_start):
        pass

    def play_instance_idle(self, iid, ci):
        pass

    def load_animation_clips(self, path):
        return [{"duration": 1.0}]


class _Char:
    def __init__(self):
        self._render_instance = 777        # already realised (like Picard post-intro)
        self._location = "DBstand"
        self._hidden = 0

    def GetCharacterName(self):
        return "Picard"

    def SetHidden(self, h):
        self._hidden = 1 if h else 0

    def IsHidden(self):
        return self._hidden

    def SetLocation(self, loc):
        self._location = loc

    def GetLocation(self):
        return self._location


def _wire(monkeypatch):
    walk = BridgeCharacterWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: walk)
    monkeypatch.setattr(bcw, "capture_breathing", lambda c: None)
    monkeypatch.setattr(
        bridge_placement, "capture_move",
        lambda character, d: {"clip_nif": "db_sit_P.nif",
                              "end_location": "DBGuest"})
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", lambda c: c)
    return walk


def test_at_move_completes_through_view_independent_pump(monkeypatch):
    """An AT_MOVE completes when driven ONLY by _pump_walk_controller — i.e.
    with no bridge view involved at all — so an undock-beat walk can never hang
    the mission sequence just because the active view isn't the bridge."""
    walk = _wire(monkeypatch)
    r = _FakeRenderer()
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P")
    act.Play()
    assert act.IsPlaying() is True
    # Drive frames through the view-independent seam — NOT the bridge render
    # block. There is no view_mode anywhere in this test.
    _pump_walk_controller(walk, r, 0.0, paused=False)      # start (realise/reveal/walk)
    assert r.walked                                        # the walk actually began
    assert ch.IsHidden() == 0
    _pump_walk_controller(walk, r, 2.0, paused=False)      # settle (clip dur 1.0)
    assert ch.GetLocation() == "DBGuest"                   # re-stationed
    assert act.IsPlaying() is False                        # completion -> sequence advances


def test_pump_skipped_while_paused(monkeypatch):
    """A paused frame freezes the walk: no progress, no completion."""
    walk = _wire(monkeypatch)
    r = _FakeRenderer()
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P")
    act.Play()
    _pump_walk_controller(walk, r, 5.0, paused=True)
    assert not r.walked                                    # never started
    assert act.IsPlaying() is True                         # still pending
