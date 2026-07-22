import engine.appc.crew_speech as crew_speech
from engine.appc.speak_queue import SpeakQueue
from engine.appc import speak_queue as sq


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


def test_add_sound_to_queue_noop_without_sound():
    q = sq.SpeakQueue(_Owner())
    q.add_sound_to_queue(None, 2, 0)
    assert q.is_ready_to_speak() == 0


def test_add_sound_to_queue_enqueues_non_immediate(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = sq.SpeakQueue(_Owner())

    class _Snd:
        def __init__(self): self.played = 0
        def Play(self): self.played += 1
    s = _Snd()
    q.add_sound_to_queue(s, 0, 0)          # type != 2 -> enqueue, don't play
    assert s.played == 0
    assert q.is_ready_to_speak() == 1      # now pending


def test_add_sound_to_queue_type2_plays_immediately_when_speaking(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: True)
    q = sq.SpeakQueue(_Owner())

    class _Snd:
        def __init__(self): self.played = 0
        def Play(self): self.played += 1
    s = _Snd()
    q.add_sound_to_queue(s, 2, 0)          # type==2 & already speaking -> play now, over the top
    assert s.played == 1
    assert q.is_ready_to_speak() == 0      # nothing enqueued


def test_add_sound_to_queue_type2_enqueues_when_fully_idle(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = sq.SpeakQueue(_Owner())

    class _Snd:
        def __init__(self): self.played = 0
        def Play(self): self.played += 1
    s = _Snd()
    q.add_sound_to_queue(s, 2, 0)          # type==2 but idle (nothing queued, not speaking) -> enqueue
    assert s.played == 0
    assert q.is_ready_to_speak() == 1      # now pending


def test_someone_speaking_reflects_bus(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    b = crew_speech.bus()
    b._active_speaker = ""
    assert sq.someone_speaking() == 0


def test_characterclass_speakline_clears_interruptable_and_emits(monkeypatch):
    from engine.appc.characters import CharacterClass
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append((name, line, prio)) or 2.0)
    ch = CharacterClass()
    ch.SetCharacterName("Kiska")
    seen = {"cleared": 0}
    monkeypatch.setattr(ch, "ClearExtraAnimations", lambda: seen.__setitem__("cleared", seen["cleared"] + 1))
    ch.SpeakLine("DB", "gh075", 1)
    assert seen["cleared"] == 1
    assert calls == [("Kiska", "gh075", 1)]


def test_characterclass_isreadytospeak_no_longer_hardcoded_one(monkeypatch):
    from engine.appc.characters import CharacterClass
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    ch = CharacterClass()
    ch.SetCharacterName("Science")
    assert ch.IsReadyToSpeak() == 0        # was a hard 1 (always-return Science bug)
