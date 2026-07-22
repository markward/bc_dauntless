import engine.appc.crew_speech as crew_speech
from engine.appc.speak_queue import SpeakQueue


class _Owner:
    def __init__(self):
        self.name = "Kiska"
        self.cleared = 0
    def GetCharacterName(self):
        return self.name
    def ClearExtraAnimations(self):
        self.cleared += 1


def test_speak_line_clears_interruptable_then_emits(monkeypatch):
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append((name, db, line, prio)) or 3.0)
    owner = _Owner()
    q = SpeakQueue(owner)
    dur = q.speak_line("DB", "gh075", 1)
    assert owner.cleared == 1                      # SpeakHelper clears cats 0,1,5,6
    assert calls == [("Kiska", "DB", "gh075", 1)]  # routed through the one funnel
    assert dur == 3.0


def test_say_line_forwards_optional_priority(monkeypatch):
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append(prio) or 0.0)
    q = SpeakQueue(_Owner())
    q.say_line("DB", "gf020", "Captain", 1, 7)     # 5-arg form: real priority is arg5
    assert calls == [7]


def test_is_ready_to_speak_is_zero_when_queue_empty(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = SpeakQueue(_Owner())
    assert q.is_ready_to_speak() == 0              # fixes the always-1 Science-guard bug
    assert q.is_speaking() == 0
