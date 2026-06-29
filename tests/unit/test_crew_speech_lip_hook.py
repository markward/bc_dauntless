"""crew_speech speech-start observer hook -- the cue source for lip-sync.

A listener registered via add_speech_listener is notified (speaker, wav,
duration, now) for every ACCEPTED line, and not for dropped lines. The hook is
decoupled from rendering so the bus stays testable without audio/GL.
"""
from engine.appc.crew_speech import (
    CrewSpeechBus,
    add_speech_listener,
    remove_speech_listener,
)
from engine.appc.ai import CSP_NORMAL, CSP_MISSION_CRITICAL, CSP_SPONTANEOUS


def test_listener_notified_for_accepted_line():
    seen = []
    fn = lambda *a: seen.append(a)
    add_speech_listener(fn)
    try:
        bus = CrewSpeechBus()
        dur = bus.speak("Picard", "Engage", "x.mp3", CSP_NORMAL, now=0.0)
        assert seen == [("Picard", "x.mp3", dur, 0.0)]
    finally:
        remove_speech_listener(fn)


def test_listener_not_notified_for_dropped_line():
    seen = []
    fn = lambda *a: seen.append(a)
    add_speech_listener(fn)
    try:
        bus = CrewSpeechBus()
        bus.speak("Felix", "Critical!", None, CSP_MISSION_CRITICAL, now=0.0)
        seen.clear()
        # Lower-priority chatter while the critical line is live -> dropped.
        bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.5)
        assert seen == []
    finally:
        remove_speech_listener(fn)


def test_listener_wav_none_when_no_voice():
    seen = []
    fn = lambda *a: seen.append(a)
    add_speech_listener(fn)
    try:
        bus = CrewSpeechBus()
        bus.speak("Data", "text only", None, CSP_NORMAL, now=1.0)
        assert seen[0][0] == "Data"
        assert seen[0][1] is None
    finally:
        remove_speech_listener(fn)


def test_remove_listener_stops_notifications():
    seen = []
    fn = lambda *a: seen.append(a)
    add_speech_listener(fn)
    remove_speech_listener(fn)
    bus = CrewSpeechBus()
    bus.speak("Picard", "Engage", "x.mp3", CSP_NORMAL, now=0.0)
    assert seen == []


def test_listener_exception_does_not_break_speak():
    def boom(*a):
        raise RuntimeError("listener blew up")

    add_speech_listener(boom)
    try:
        bus = CrewSpeechBus()
        assert bus.speak("Picard", "Engage", "x.mp3", CSP_NORMAL, now=0.0) > 0.0
    finally:
        remove_speech_listener(boom)
