"""CrewSpeechBus arbitration + duration. Pure logic -- no top window, no audio
(routing degrades to no-op when collaborators are absent)."""
from engine.appc.crew_speech import CrewSpeechBus, _estimate_duration
from engine.appc.ai import CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL


def test_first_line_is_accepted():
    bus = CrewSpeechBus()
    assert bus.speak("Helm", "Course laid in", None, CSP_NORMAL, now=0.0) > 0.0


def test_lower_priority_dropped_while_line_live():
    bus = CrewSpeechBus()
    bus.speak("Felix", "Mission critical!", None, CSP_MISSION_CRITICAL, now=0.0)
    # Spontaneous chatter arrives 1s later, line still live -> dropped.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=1.0) == 0.0


def test_equal_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("A", "one", None, CSP_NORMAL, now=0.0)
    assert bus.speak("B", "two", None, CSP_NORMAL, now=0.5) > 0.0


def test_higher_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.0)
    assert bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.5) > 0.0


def test_expired_line_lets_lower_priority_through():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    # Far past the max 8s dwell -> channel free.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=100.0) > 0.0


def test_reset_frees_the_channel():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    bus.reset()
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.1) > 0.0


def test_voice_only_line_is_accepted():
    # SayLine path: text=None, wav present. Must not block on the absent text.
    bus = CrewSpeechBus()
    assert bus.speak("Helm", None, "sounds/aye.wav", CSP_NORMAL, now=0.0) > 0.0


def test_empty_line_with_no_text_or_wav_is_dropped():
    # A line with nothing to say must not occupy the channel.
    bus = CrewSpeechBus()
    assert bus.speak("Helm", None, None, CSP_MISSION_CRITICAL, now=0.0) == 0.0
    # ...and the channel stays free for the next real line.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.1) > 0.0


def test_duration_clamps_between_2_and_8_seconds():
    assert _estimate_duration("hi", None) == 2.0                 # 1 word -> floored
    assert _estimate_duration(None, None) == 2.0                 # empty -> floored
    long_text = " ".join(["word"] * 100)
    assert _estimate_duration(long_text, None) == 8.0            # capped


def test_speak_returns_estimate_duration_for_text_only():
    bus = CrewSpeechBus()
    # Text-only line (no wav): duration is the word-estimate, > 0.
    dur = bus.speak("Liu", "Captain, welcome to Starbase 12.", None, 1, now=0.0)
    assert dur > 0.0
    assert bus._active_expiry == dur           # bus expiry uses the same value


def test_speak_dropped_line_returns_zero():
    bus = CrewSpeechBus()
    assert bus.speak("Liu", None, None, 1, now=0.0) == 0.0   # nothing to say


class _FakeHandle:
    """Stands in for tg_sound._PlayingSound — records Stop() calls."""
    def __init__(self, tag, stopped):
        self.tag = tag
        self._stopped = stopped
    def Stop(self):
        self._stopped.append(self.tag)


def test_preempting_line_stops_previous_voice():
    # Two overlapping accepted lines (e.g. Graff's greeting + Liu's briefing)
    # must not play simultaneously: the new line takes the single VO channel and
    # the previous voice is stopped. Regression for two-admirals-talking-at-once.
    bus = CrewSpeechBus()
    stopped = []
    handles = iter([_FakeHandle("graff", stopped), _FakeHandle("liu", stopped)])
    bus._play_voice = lambda wav: (5.0, next(handles))      # (duration, handle)

    bus.speak("Graff", None, "graff.mp3", 1, now=0.0)
    assert stopped == []                                     # nothing to stop yet
    bus.speak("Liu", None, "liu.mp3", 1, now=1.0)            # graff still live -> preempt
    assert stopped == ["graff"]                              # graff's voice was stopped


def test_dropped_line_does_not_stop_active_voice():
    bus = CrewSpeechBus()
    stopped = []
    handles = iter([_FakeHandle("hi", stopped)])
    bus._play_voice = lambda wav: (5.0, next(handles))
    bus.speak("XO", None, "hi.mp3", 2, now=0.0)             # high priority, live
    bus.speak("Helm", None, "low.mp3", 0, now=1.0)          # lower priority -> dropped
    assert stopped == []                                    # the live line keeps playing


def test_reset_stops_active_voice():
    bus = CrewSpeechBus()
    stopped = []
    bus._play_voice = lambda wav: (5.0, _FakeHandle("x", stopped))
    bus.speak("XO", None, "x.mp3", 1, now=0.0)
    bus.reset()
    assert stopped == ["x"]
