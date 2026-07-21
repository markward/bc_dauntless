"""CharacterAction's AT_TURN/AT_TURN_BACK verbs, re-pointed (SP2 T14b) through
the CharacterClass door (TurnTowards/TurnBack) instead of calling the turn
controller directly. The CharacterClass AnimRec queue now owns the actual
controller call (via UpdateAnimationQueue -> play_record); CharacterAction
only enqueues and waits for its on_complete to fire.

NOTE (flagged deviation, see docs/superpowers/plans/2026-07-21-characterclass-
sp2-animation-queue.md progress ledger): AT_TURN_NOW no longer completes
INLINE at Play() -- it enqueues like AT_TURN, and `now` only threads through
to the eventual controller call. This adds ~1 queue-drain of latency vs stock
BC's synchronous turn-and-continue; a live pass should verify this is
imperceptible.

The CAT_TURN_BACK follow-up (Special4: composing "<Location>Back<Target>" and
resolving/playing it) is exercised separately in test_character_anim_queue.py
-- these tests stay at the CharacterAction routing seam and don't re-drive it.
"""
from engine.appc.ai import CharacterAction
from engine.appc.characters import CharacterClass_Create
import engine.bridge_character_anim as bca


def _char(active=True):
    ch = CharacterClass_Create()
    if active:
        ch.SetActive(1)
    return ch


def _real_controller_recording_turns(monkeypatch):
    """A real BridgeCharacterAnimController with request_turn_to swapped for a
    recording fake -- so play_record/is_active/stop stay the genuine
    plumbing the CharacterClass queue calls, and only the turn call itself
    is observed."""
    ctrl = bca.BridgeCharacterAnimController()
    calls = []

    def _recording_request_turn_to(character, detail, *, back=False, hold=True,
                                   now=False, on_complete=None):
        calls.append(dict(character=character, detail=detail, back=back,
                          now=now, on_complete=on_complete))

    monkeypatch.setattr(ctrl, "request_turn_to", _recording_request_turn_to)
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    return ctrl, calls


def test_at_turn_queues_and_defers(monkeypatch):
    ch = _char()
    ctrl, calls = _real_controller_recording_turns(monkeypatch)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is True                     # deferred
    assert len(ch._anim_pending) == 1
    rec = ch._anim_pending[0]
    assert rec.category == ch.CAT_TURN
    assert rec.name == "Captain"
    assert rec.now is False
    assert rec.on_complete == act.Completed

    ch.UpdateAnimationQueue()                          # drains the queue -> plays
    assert len(calls) == 1
    c = calls[0]
    assert (c["detail"], c["back"], c["now"]) == ("Captain", False, False)
    c["on_complete"]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_turn_now_still_defers_until_the_queue_drains(monkeypatch):
    ch = _char()
    ctrl, calls = _real_controller_recording_turns(monkeypatch)
    act = CharacterAction(ch, CharacterAction.AT_TURN_NOW, "Captain")
    act.Play()
    assert act.IsPlaying() is True                     # no longer inline (see module docstring)

    ch.UpdateAnimationQueue()
    assert calls[0]["now"] is True
    calls[0]["on_complete"]()
    assert act.IsPlaying() is False


def test_at_turn_non_captain_detail_is_a_captain_only_noop(monkeypatch):
    # tier-0 §4.10: TurnTowards only acts for name == "Captain"; any other
    # detail no-ops, firing on_complete inline so the sequence never hangs.
    ch = _char()
    ctrl, calls = _real_controller_recording_turns(monkeypatch)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Science")
    act.Play()
    assert act.IsPlaying() is False
    assert ch._anim_pending == []
    assert calls == []


def test_at_turn_back_enqueues_via_turnback(monkeypatch):
    ch = _char()
    ctrl, calls = _real_controller_recording_turns(monkeypatch)
    back = CharacterAction(ch, CharacterAction.AT_TURN_BACK)
    back.Play()
    assert back.IsPlaying() is True
    assert len(ch._anim_pending) == 1
    rec = ch._anim_pending[0]
    assert rec.category == ch.CAT_TURN_BACK
    assert rec.now is False
    assert rec.on_complete == back.Completed

    rec.on_complete()                                  # completion guarantee fires
    assert back.IsPlaying() is False


def test_at_turn_back_now_threads_now_onto_the_record(monkeypatch):
    ch = _char()
    ctrl, calls = _real_controller_recording_turns(monkeypatch)
    back = CharacterAction(ch, CharacterAction.AT_TURN_BACK_NOW)
    back.Play()
    rec = ch._anim_pending[0]
    assert rec.now is True


def test_queue_turn_exception_is_best_effort(monkeypatch):
    # If CharacterClass_Cast (or TurnTowards/TurnBack) blows up, Play() must
    # not propagate and the action must complete inline so the mission
    # TGSequence advances.
    ch = _char()

    def boom(obj):
        raise RuntimeError("cast blew up")

    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", boom)

    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()                                          # must not raise
    assert act.IsPlaying() is False                     # completed inline


def test_at_turn_completes_inline_when_character_cast_is_none(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda obj: None)
    act = CharacterAction(_char(), CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is False
