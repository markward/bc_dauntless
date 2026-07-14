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
