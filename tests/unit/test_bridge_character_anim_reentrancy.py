"""Re-entrancy safety for BridgeCharacterAnimController.update().

Event dispatch is SYNCHRONOUS (engine/appc/events.py). An _Action's on_complete
is now a CharacterAction's Completed(), which advances the owning TGSequence,
which immediately Play()s the NEXT CharacterAction -- and that action can
submit()/request_default() on the same or another officer, RE-ENTERING the
controller from inside update()'s own loop.

Two invariants must hold on every path:
  * _current_anim must never leak (an action that is stored must always reach
    its on_complete), or IsAnimatingNonInterruptable() jams shut forever;
  * every stored on_complete fires exactly once, or the mission TGSequence that
    is waiting on it freezes forever.

These tests drive the REAL controller (not a fake that completes turns
synchronously), so the queue -> update() -> drain semantics are exercised.
"""
from engine.bridge_character_anim import (
    BridgeCharacterAnimController, _SCRIPTED, _TURN, _IDLE)


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
        return [{"duration": self._dur,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _Char:
    def __init__(self, iid):
        self._render_instance = iid

    def IsHidden(self):
        return 0


def test_reentrant_submit_on_another_officer_during_update(monkeypatch):
    # The completing action's callback Play()s the next CharacterAction, which
    # gestures a DIFFERENT officer -> a NEW key in _active. Iterating _active
    # directly blew up with `RuntimeError: dictionary changed size during
    # iteration`, thrown straight out of char_anim.update() in the host loop.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    picard, brex = _Char(1), _Char(2)
    fired = []

    def _next_action():
        fired.append("picard")
        ctrl.submit(brex, [("brex.nif", 0.0)], priority=_SCRIPTED,
                    on_complete=lambda: fired.append("brex"))

    ctrl.submit(picard, [("picard.nif", 0.0)], priority=_SCRIPTED,
                on_complete=_next_action)
    ctrl.update(0.0, renderer=r)          # start Picard's clip
    ctrl.update(2.0, renderer=r)          # settle -> re-entrant submit on Brex
    assert fired == ["picard"]

    ctrl.update(0.0, renderer=r)          # Brex's clip starts
    ctrl.update(2.0, renderer=r)          # ...and settles
    assert fired == ["picard", "brex"]
    assert ctrl.is_busy(brex) is False    # nothing leaked


def test_reentrant_request_default_during_update(monkeypatch):
    # AT_PLAY_ANIMATION followed by AT_DEFAULT is the most idiomatic SDK pairing
    # there is. AT_DEFAULT -> request_default() -> _active.pop() from inside the
    # update() loop -> the dict shrinks mid-iteration.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char(5)
    fired = []

    ctrl.submit(ch, [("gesture.nif", 0.0)], priority=_SCRIPTED,
                on_complete=lambda: (fired.append(True), ctrl.request_default(ch)))
    ctrl.update(0.0, renderer=r)
    ctrl.update(2.0, renderer=r)          # settle -> re-entrant request_default
    assert fired == [True]

    ctrl.update(0.0, renderer=r)          # drains _pending_defaults
    assert ctrl.is_busy(ch) is False       # no leak
    assert r.restored == [5, 5]            # rest pose restored (settle + default)


def test_reentrant_submit_on_the_same_officer_is_not_clobbered(monkeypatch):
    # A _SCRIPTED (2) gesture submitted from the callback of a settling _TURN (1)
    # on the SAME officer is accepted by submit() and stored under the same iid.
    # The old post-loop `for iid in done: self._active.pop(iid)` then popped the
    # BRAND-NEW action: its on_complete never fired (mission TGSequence frozen)
    # and cc._current_anim leaked (IsAnimatingNonInterruptable() jammed shut).
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char(9)
    fired = []

    def _turn_done():
        fired.append("turn")
        assert ctrl.submit(ch, [("gesture.nif", 0.0)], priority=_SCRIPTED,
                           on_complete=lambda: fired.append("gesture")) is True

    ctrl.submit(ch, [("turn.nif", 0.0)], priority=_TURN, hold=True,
                on_complete=_turn_done)
    ctrl.update(0.0, renderer=r)
    ctrl.update(2.0, renderer=r)          # turn settles -> re-entrant gesture
    assert fired == ["turn"]
    # The replacement action must still be live -- not popped by the finisher.
    assert ctrl.is_busy(ch) is True

    ctrl.update(0.0, renderer=r)          # gesture starts
    ctrl.update(2.0, renderer=r)          # gesture settles
    assert fired == ["turn", "gesture"]   # sequence advanced; nothing leaked
    assert ctrl.is_busy(ch) is False


def test_submit_preemption_rescues_the_preempted_on_complete():
    # _SCRIPTED (2) is the first band that can preempt a callback-carrying
    # _TURN (1) -- e.g. a scripted gesture landing on an officer who is mid
    # turn-to-captain for an AT_SAY_LINE (callback = speak-then-turn-back).
    # Dropping that callback means the line never speaks and the owning
    # TGSequence stalls forever. _process_turn and request_default both already
    # rescue-and-fire; submit() must too.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=5.0)       # long clip: the turn is still in flight
    ch = _Char(3)
    turn_fired = []
    gesture_fired = []

    ctrl.submit(ch, [("turn.nif", 0.0)], priority=_TURN, hold=True,
                on_complete=lambda: turn_fired.append(True))
    ctrl.update(0.0, renderer=r)
    ctrl.update(0.5, renderer=r)          # mid-clip, unsettled
    assert turn_fired == []

    assert ctrl.submit(ch, [("gesture.nif", 0.0)], priority=_SCRIPTED,
                       on_complete=lambda: gesture_fired.append(True)) is True
    assert turn_fired == [True]           # rescued, exactly once

    ctrl.update(0.0, renderer=r)
    ctrl.update(10.0, renderer=r)         # the preempting gesture settles
    assert gesture_fired == [True]
    assert turn_fired == [True]           # never double-fired


def test_submit_preemption_rescue_sees_updated_state():
    # Ordering hazard: the rescued callback must run only AFTER _active[iid] has
    # been replaced, or a re-entrant call from it sees stale state (the same
    # discipline request_default already uses).
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=5.0)
    ch = _Char(4)
    seen = []

    ctrl.submit(ch, [("idle.nif", 0.0)], priority=_IDLE,
                on_complete=lambda: seen.append(ctrl.is_busy(ch)))
    ctrl.update(0.0, renderer=r)
    ctrl.submit(ch, [("gesture.nif", 0.0)], priority=_SCRIPTED)
    assert seen == [True]                 # the NEW action is already installed
