"""Regression: CharacterClass.UpdateAnimationQueue() must be driven every
unpaused frame, BEFORE char_anim.update() drains its pending lists.

E1M1's Picard intro runs AT_WATCH_ME -> AT_TURN "Captain" -> AT_STOP_WATCHING_ME
(E1M1.py:2547-2550). AT_TURN enqueues a record into CharacterClass's own
animation queue, but nothing in the host loop ever called
UpdateAnimationQueue() to play it and fire its on_complete (the
CharacterAction.Completed() that advances the mission TGSequence). The turn
never played, the sequence stalled before AT_STOP_WATCHING_ME, and the camera
stayed locked on Picard forever.

_pump_character_queues is the small, testable helper that drives each active
bridge officer's queue one step; _pump_char_anim calls it before
char_anim.update() so a record queued this frame is visible to the controller
before it drains.
"""
from engine.host_loop import _pump_character_queues, _pump_char_anim


class _CountingChar:
    def __init__(self):
        self.calls = 0

    def UpdateAnimationQueue(self):
        self.calls += 1


class _RaisingChar:
    def __init__(self):
        self.calls = 0

    def UpdateAnimationQueue(self):
        self.calls += 1
        raise RuntimeError("boom")


class _NoQueueChar:
    """A character with no UpdateAnimationQueue at all (must be skipped, not
    crash)."""


def test_pump_character_queues_calls_update_animation_queue_on_each():
    c1 = _CountingChar()
    c2 = _CountingChar()
    _pump_character_queues([c1, c2])
    assert c1.calls == 1
    assert c2.calls == 1


def test_pump_character_queues_raising_character_does_not_stop_the_rest():
    bad = _RaisingChar()
    good = _CountingChar()
    _pump_character_queues([bad, good])
    assert bad.calls == 1
    assert good.calls == 1


def test_pump_character_queues_skips_characters_without_the_method():
    no_queue = _NoQueueChar()
    good = _CountingChar()
    # Must not raise.
    _pump_character_queues([no_queue, good])
    assert good.calls == 1


class _FakeCharAnim:
    def __init__(self):
        self.calls = []

    def update(self, dt, renderer=None, anim_mgr=None):
        self.calls.append(("update", dt))


def test_pump_char_anim_pumps_queues_before_char_anim_update(monkeypatch):
    order = []

    def fake_pump_character_queues(characters):
        order.append("queues")

    def fake_live_bridge_characters():
        return []

    monkeypatch.setattr("engine.host_loop._pump_character_queues",
                        fake_pump_character_queues)
    monkeypatch.setattr("engine.host_loop._live_bridge_characters",
                        fake_live_bridge_characters)

    char_anim = _FakeCharAnim()
    orig_update = char_anim.update

    def recording_update(dt, renderer=None, anim_mgr=None):
        order.append("update")
        return orig_update(dt, renderer=renderer, anim_mgr=anim_mgr)

    char_anim.update = recording_update

    _pump_char_anim(char_anim, renderer=object(), dt=0.1, paused=False)

    assert order == ["queues", "update"]


def test_pump_char_anim_skips_queues_and_update_while_paused(monkeypatch):
    calls = []

    def fake_pump_character_queues(characters):
        calls.append("queues")

    monkeypatch.setattr("engine.host_loop._pump_character_queues",
                        fake_pump_character_queues)

    char_anim = _FakeCharAnim()
    _pump_char_anim(char_anim, renderer=object(), dt=0.1, paused=True)

    assert calls == []
    assert char_anim.calls == []
