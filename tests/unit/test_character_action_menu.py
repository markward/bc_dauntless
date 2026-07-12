"""AT_MENU_UP / AT_MENU_DOWN are the sequenceable wrappers around BC's
CharacterClass.MenuUp()/MenuDown() (E1M1 crew-intro, E8M2 Liu, QB intro).

A SCRIPTED menu-up must NOT acknowledge -- BC plays "Yes sir" in
CharacterInteraction on the click path only; otherwise officers would bark over
the mission's own dialogue.
"""
from engine.appc.ai import CharacterAction


class _Char:
    def __init__(self):
        self.up_calls = 0
        self.down_calls = 0
    def GetCharacterName(self):
        return "Brex"
    def MenuUp(self):
        self.up_calls += 1
        return 1
    def MenuDown(self):
        self.down_calls += 1


def _patch_cast(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", lambda c: c)


def test_at_menu_up_raises_menu_and_completes_inline(monkeypatch):
    _patch_cast(monkeypatch)
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MENU_UP)
    act.Play()
    assert ch.up_calls == 1
    assert act.IsPlaying() is False          # inline: open/close is instant


def test_at_menu_down_lowers_menu_and_completes_inline(monkeypatch):
    _patch_cast(monkeypatch)
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_MENU_DOWN)
    act.Play()
    assert ch.down_calls == 1
    assert act.IsPlaying() is False


def test_scripted_menu_up_does_not_acknowledge(monkeypatch):
    """The ack trap: BC acks in CharacterInteraction (click path), NOT MenuUp."""
    _patch_cast(monkeypatch)
    acks = []
    from engine.appc import crew_speech
    monkeypatch.setattr(crew_speech, "acknowledge",
                        lambda char: acks.append(char), raising=False)
    ch = _Char()
    CharacterAction(ch, CharacterAction.AT_MENU_UP).Play()
    assert acks == []                        # silent under a mission sequence


def test_at_menu_up_completes_inline_when_cast_fails(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: None)
    act = CharacterAction(_Char(), CharacterAction.AT_MENU_UP)
    act.Play()
    assert act.IsPlaying() is False          # never stalls the sequence


def test_at_menu_up_does_not_raise_when_menuup_raises(monkeypatch):
    _patch_cast(monkeypatch)

    class _Boom(_Char):
        def MenuUp(self):
            raise RuntimeError("boom")

    act = CharacterAction(_Boom(), CharacterAction.AT_MENU_UP)
    act.Play()                                # must not propagate
    assert act.IsPlaying() is False
