from engine.appc.characters import CharacterClass
from engine.appc import crew_speech
from engine.core import stub_telemetry


def test_unknown_setter_is_recorded_in_stub_telemetry():
    stub_telemetry.reset()
    stub_telemetry.set_enabled(True)
    try:
        ch = CharacterClass("body.nif", "head.nif")
        ch.SetLookAtAdj(0, 0, 51)          # real SDK call (Felix.py:247), unimplemented
        snap = stub_telemetry.snapshot()
    finally:
        stub_telemetry.set_enabled(False)
        stub_telemetry.reset()
    assert any(
        "LookAtAdj" in str(k) for bucket in snap.values() for k in bucket
    ), snap


def test_numeric_getters_return_floats_not_none():
    ch = CharacterClass("body.nif", "head.nif")
    assert ch.GetBlinkChance() == 0.1              # BC's ctor default
    assert isinstance(ch.GetRandomAnimationChance(), float)
    ch.SetRandomAnimationChance(0.75)
    assert ch.GetRandomAnimationChance() == 0.75


def test_is_speaking_tracks_the_active_speaker():
    bus = crew_speech.bus()
    bus.reset()
    # speak() takes (speaker, text, wav, priority, now); a text-only line gets an
    # estimated duration >= _MIN_DURATION_S (2.0s).
    dur = bus.speak("Kiska", "Aye, Captain.", None, 1, now=100.0)
    assert dur > 0.0
    assert crew_speech.is_speaking("Kiska", now=100.5) is True
    assert crew_speech.is_speaking("Felix", now=100.5) is False   # no cross-talk
    assert crew_speech.is_speaking("Kiska", now=100.0 + dur + 0.1) is False
    bus.reset()


def test_skip_current_clears_active_speaker():
    """After skip_current(), is_speaking() must be False and _active_speaker must be empty."""
    bus = crew_speech.bus()
    bus.reset()
    # Speak a line and verify it's active
    dur = bus.speak("Helm", "Course laid in.", None, 1, now=200.0)
    assert dur > 0.0
    assert crew_speech.is_speaking("Helm", now=200.5) is True
    assert bus._active_speaker == "Helm"
    # Skip the line
    bus.skip_current(now=200.5)
    # Verify the speaker is cleared and is_speaking() reports False
    assert crew_speech.is_speaking("Helm", now=200.5) is False
    assert bus._active_speaker == ""
    bus.reset()


def test_cat_constants_are_bc_ordinals():
    # BC's CAT_ values are plain ordinals 0..6, proven from the binary's own
    # predicates: IsAnimatingInterruptable accepts {0,1,5,6}; IsAnimatingNon-
    # Interruptable tests == 2.
    assert CharacterClass.CAT_BREATHE == 0
    assert CharacterClass.CAT_INTERRUPTABLE == 1
    assert CharacterClass.CAT_NON_INTERRUPTABLE == 2
    assert CharacterClass.CAT_TURN == 3
    assert CharacterClass.CAT_TURN_BACK == 4
    assert CharacterClass.CAT_GLANCE == 5
    assert CharacterClass.CAT_GLANCE_BACK == 6


class _ActiveController:
    """Fake clip-player controller reporting a current animation as live,
    mirroring 'an animation is playing on this officer' for the queue model's
    ReleaseCurrentAnimation gate (see CharacterClass._anim_is_active)."""

    def is_active(self, character):
        return True

    def stop(self, character):
        pass

    def play_record(self, character, rec):
        pass


def test_non_interruptable_animation_closes_the_sdk_gate(monkeypatch):
    import engine.bridge_character_anim as bridge_character_anim
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: _ActiveController())

    ch = CharacterClass("body.nif", "head.nif")
    assert ch.IsAnimating() == 0
    assert ch.IsAnimatingNonInterruptable() == 0

    ch.set_current_animation("PushingButtons", CharacterClass.CAT_NON_INTERRUPTABLE)
    assert ch.IsAnimating() == 1
    assert ch.IsGoingToAnimate() == 1
    assert ch.IsAnimatingNonInterruptable() == 1
    assert ch.IsAnimatingInterruptable() == 0
    assert ch.GetCurrentAnimation() == "PushingButtons"

    ch.clear_current_animation()
    assert ch.IsAnimating() == 0
    assert ch.IsAnimatingNonInterruptable() == 0


def test_interruptable_categories_match_the_binary(monkeypatch):
    import engine.bridge_character_anim as bridge_character_anim
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: _ActiveController())

    ch = CharacterClass("body.nif", "head.nif")
    for cat in (CharacterClass.CAT_BREATHE, CharacterClass.CAT_INTERRUPTABLE,
                CharacterClass.CAT_GLANCE, CharacterClass.CAT_GLANCE_BACK):
        ch.set_current_animation("x", cat)
        assert ch.IsAnimatingInterruptable() == 1, cat
        assert ch.IsAnimatingNonInterruptable() == 0, cat
    ch.set_current_animation("x", CharacterClass.CAT_NON_INTERRUPTABLE)
    assert ch.IsAnimatingInterruptable() == 0
