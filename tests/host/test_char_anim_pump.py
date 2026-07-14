"""Regression: a say-line's turn must NOT be gated on bridge view.

_queue_say_line defers the SPEECH ITSELF behind request_turn_to(...,
on_complete=_speak) for AT_SAY_LINE_AFTER_TURN. request_turn_to only QUEUES into
_pending_turns; the queue is drained by BridgeCharacterAnimController.update().

The ONLY call site of char_anim.update() used to sit inside the host loop's
``if view_mode.is_bridge:`` render block. So any turned say-line issued while the
player was in tactical/exterior view had its turn queued, the deferred speak
never ran, the line was never spoken and the mission TGSequence hung until the
player happened to switch to bridge view.

``_pump_char_anim`` is the view-independent seam (alongside _pump_walk_controller
and _pump_bridge_doors) that runs every unpaused frame regardless of view. These
tests drive a say-line to completion through that seam alone — with no bridge
view anywhere.

NOTE the verbs differ (Ghidra ground truth, docs/gameplay/
bridge-character-system.md §8.3): AT_SAY_LINE_AFTER_TURN awaits its opening turn
(so its speech is what the pump releases), while AT_SAY_LINE overlaps the turn
with the line and speaks immediately — its turn still has to reach the renderer
through this same pump, and its turn-back is fire-and-forget.
"""
import App
from engine import bridge_character_anim
from engine.appc.ai import CharacterAction
from engine.bridge_character_anim import BridgeCharacterAnimController
from engine.host_loop import _pump_char_anim


class _FakeRenderer:
    def __init__(self, clip_dur=1.0):
        self._next = 10
        self._dur = clip_dur
        self.gestures = []
        self.idled = []
        self.restored = []

    def load_instance_clip(self, iid, path):
        self._next += 1
        return self._next

    def play_instance_gesture(self, iid, ci):
        self.gestures.append((iid, ci))

    def play_instance_idle(self, iid, ci):
        self.idled.append((iid, ci))

    def restore_rest_pose(self, iid):
        self.restored.append(iid)

    def load_animation_clips(self, path):
        # non-empty + rotation track => body-driven officer (turn defers)
        return [{"duration": self._dur,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _Char:
    def __init__(self, iid=42):
        self._render_instance = iid

    def GetCharacterName(self):
        return "Helm"

    def IsHidden(self):
        return 0


def _wire(monkeypatch):
    ctrl = BridgeCharacterAnimController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_character_anim, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": suffix + ".nif"})
    monkeypatch.setattr(bridge_character_anim, "capture_chair_clip",
                        lambda ch, suffix: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    return ctrl


def test_say_line_after_turn_completes_through_the_view_independent_pump(
        monkeypatch):
    """The line SPEAKS and the action COMPLETES when driven only by
    _pump_char_anim — i.e. with no bridge view involved at all."""
    ctrl = _wire(monkeypatch)
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    act = CharacterAction(ch, CharacterAction.AT_SAY_LINE_AFTER_TURN,
                          "IncomingMsg6", "Captain", 1)
    act.Play()
    assert act.IsPlaying() is True
    assert spoken == []                          # deferred behind the turn

    # Frames through the view-independent seam ONLY. No view_mode in this test.
    _pump_char_anim(ctrl, r, 0.0, paused=False)  # drain -> submit the body turn
    assert spoken == []
    _pump_char_anim(ctrl, r, 2.0, paused=False)  # turn settles -> speak
    assert spoken == ["IncomingMsg6"]

    App.g_kRealtimeTimerManager.tick(1.5)        # line plays out -> turn back
    assert act.IsPlaying() is False              # completes AT END-OF-LINE...
    _pump_char_anim(ctrl, r, 0.0, paused=False)  # ...with the swivel starting now
    assert ctrl.is_busy(ch) is True              # the turn-back genuinely plays
    _pump_char_anim(ctrl, r, 2.0, paused=False)  # and settles underneath
    assert ctrl.is_busy(ch) is False             # nothing leaked


def test_say_line_speaks_at_once_and_still_turns_through_the_pump(monkeypatch):
    """AT_SAY_LINE overlaps: the line starts immediately (no pump needed), while
    the turn itself still reaches the renderer through the view-independent pump."""
    ctrl = _wire(monkeypatch)
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    act = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                          "IncomingMsg6", "Captain", 1)
    act.Play()
    assert spoken == ["IncomingMsg6"]            # speaks while still turning
    assert act.IsPlaying() is True               # the line still blocks
    assert ctrl._pending_turns != []             # the turn is queued for the pump

    _pump_char_anim(ctrl, r, 0.0, paused=False)  # drain -> submit the body turn
    assert ctrl.is_busy(ch) is True

    App.g_kRealtimeTimerManager.tick(1.5)        # line plays out
    assert act.IsPlaying() is False              # completes at end-of-line
    _pump_char_anim(ctrl, r, 0.0, paused=False)
    _pump_char_anim(ctrl, r, 2.0, paused=False)  # the turn-back settles
    assert ctrl.is_busy(ch) is False             # nothing leaked


def test_pending_queues_drain_without_bridge_view(monkeypatch):
    """The minimum contract: _pending_turns / _pending_glances /
    _pending_defaults all drain through the view-independent pump."""
    ctrl = _wire(monkeypatch)
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char(43)
    ctrl.request_turn_to(ch, "Captain")
    ctrl.request_glance(_Char(44), "Away")
    ctrl.request_default(_Char(45))

    _pump_char_anim(ctrl, r, 0.0, paused=False)

    assert ctrl._pending_turns == []
    assert ctrl._pending_glances == []
    assert ctrl._pending_defaults == []


def test_char_anim_pump_skipped_while_paused(monkeypatch):
    """A paused frame freezes the controller: nothing drains, nothing speaks."""
    ctrl = _wire(monkeypatch)
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    act = CharacterAction(ch, CharacterAction.AT_SAY_LINE_AFTER_TURN,
                          "IncomingMsg6", "Captain", 1)
    act.Play()
    _pump_char_anim(ctrl, r, 5.0, paused=True)
    assert ctrl._pending_turns != []              # still queued
    assert spoken == []
    assert act.IsPlaying() is True
