"""CrewSpeechBus arbitration + duration. Pure logic -- no top window, no audio
(routing degrades to no-op when collaborators are absent)."""
from engine.appc.crew_speech import CrewSpeechBus, _estimate_duration
from engine.appc.ai import CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL


def test_first_line_is_accepted():
    bus = CrewSpeechBus()
    assert bus.speak("Helm", "Course laid in", None, CSP_NORMAL, now=0.0) is True


def test_lower_priority_dropped_while_line_live():
    bus = CrewSpeechBus()
    bus.speak("Felix", "Mission critical!", None, CSP_MISSION_CRITICAL, now=0.0)
    # Spontaneous chatter arrives 1s later, line still live -> dropped.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=1.0) is False


def test_equal_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("A", "one", None, CSP_NORMAL, now=0.0)
    assert bus.speak("B", "two", None, CSP_NORMAL, now=0.5) is True


def test_higher_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.0)
    assert bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.5) is True


def test_expired_line_lets_lower_priority_through():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    # Far past the max 8s dwell -> channel free.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=100.0) is True


def test_reset_frees_the_channel():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    bus.reset()
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.1) is True


def test_voice_only_line_is_accepted():
    # SayLine path: text=None, wav present. Must not block on the absent text.
    bus = CrewSpeechBus()
    assert bus.speak("Helm", None, "sounds/aye.wav", CSP_NORMAL, now=0.0) is True


def test_empty_line_with_no_text_or_wav_is_dropped():
    # A line with nothing to say must not occupy the channel.
    bus = CrewSpeechBus()
    assert bus.speak("Helm", None, None, CSP_MISSION_CRITICAL, now=0.0) is False
    # ...and the channel stays free for the next real line.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.1) is True


def test_duration_clamps_between_2_and_8_seconds():
    assert _estimate_duration("hi", None) == 2.0                 # 1 word -> floored
    assert _estimate_duration(None, None) == 2.0                 # empty -> floored
    long_text = " ".join(["word"] * 100)
    assert _estimate_duration(long_text, None) == 8.0            # capped
