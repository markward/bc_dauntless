"""An officer's second line at the same priority waits for his first.

Measured on the original (stbc-oracle line probe, native Windows, Quick Battle
win): QuickBattle.ShipDestroyed plays Felix's "destroyed" line in one sequence
and GenerateWinSequence plays QBFelixWin in another at the same instant, both
priority 1. The first ended 3.555 s later (clip 3.553 s) and the second 1.640 s
after that (clip 1.646 s): it began as the first ended. Dauntless's speech bus
let it cut the first."""
from engine.appc import crew_speech

LENGTHS = {"QBEnemyBOPDestroyed.mp3": 3.553, "QBFelixWin.mp3": 1.646, "Kiska.mp3": 2.0}


class _Handle:
    def __init__(self, wav, log):
        self.wav, self.log = wav, log

    def Stop(self):
        self.log.append(("stop", self.wav))


def _bus(monkeypatch):
    b = crew_speech.CrewSpeechBus()
    played = []

    def play(wav):
        played.append(("play", wav))
        return LENGTHS[wav], _Handle(wav, played)
    monkeypatch.setattr(b, "_play_voice", play)
    monkeypatch.setattr(b, "_voice_length", lambda wav: LENGTHS[wav])
    monkeypatch.setattr(b, "_route_subtitle", lambda *a: None)
    monkeypatch.setattr(crew_speech, "_notify_speech", lambda *a, **k: None)
    return b, played


def test_the_second_line_starts_as_the_first_ends(monkeypatch):
    b, played = _bus(monkeypatch)
    d1 = b.speak("Tactical", "destroyed", "QBEnemyBOPDestroyed.mp3", 1, now=100.0)
    d2 = b.speak("Tactical", "win", "QBFelixWin.mp3", 1, now=100.0)
    assert d1 == 3.553
    assert abs(d2 - (3.553 + 1.646)) < 1e-9     # its action completes after its own line
    assert played == [("play", "QBEnemyBOPDestroyed.mp3")]     # not cut, not started
    b.pump(now=103.0)
    assert len(played) == 1
    b.pump(now=103.553)
    assert played == [("play", "QBEnemyBOPDestroyed.mp3"), ("play", "QBFelixWin.mp3")]


def test_another_officer_still_takes_the_channel(monkeypatch):
    b, played = _bus(monkeypatch)
    b.speak("Tactical", "destroyed", "QBEnemyBOPDestroyed.mp3", 1, now=0.0)
    b.speak("Helm", "kiska", "Kiska.mp3", 1, now=1.0)
    assert ("stop", "QBEnemyBOPDestroyed.mp3") in played
    assert played[-1] == ("play", "Kiska.mp3")


def test_a_more_important_line_from_the_same_officer_still_cuts(monkeypatch):
    b, played = _bus(monkeypatch)
    b.speak("Tactical", "destroyed", "QBEnemyBOPDestroyed.mp3", 1, now=0.0)
    b.speak("Tactical", "critical", "QBFelixWin.mp3", 0, now=1.0)
    assert ("stop", "QBEnemyBOPDestroyed.mp3") in played
    assert played[-1] == ("play", "QBFelixWin.mp3")


def test_a_line_asked_for_in_a_later_tick_still_cuts(monkeypatch):
    """Only lines asked for in the tick the live one started wait (the
    measured case: two sequences started together). A sequence's next line,
    asked for a tick later while the wall clock still counts the last one as
    live, cuts it as before."""
    b, played = _bus(monkeypatch)
    t = [10.0]
    monkeypatch.setattr(crew_speech, "_game_time", lambda: t[0])
    b.speak("Tactical", "destroyed", "QBEnemyBOPDestroyed.mp3", 1, now=100.0)
    t[0] = 10.0 + 1.0 / 60.0
    b.speak("Tactical", "win", "QBFelixWin.mp3", 1, now=100.5)
    assert ("stop", "QBEnemyBOPDestroyed.mp3") in played
    assert played[-1] == ("play", "QBFelixWin.mp3")
