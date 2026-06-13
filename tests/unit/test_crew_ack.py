"""crew_speech.acknowledge -- the visible (subtitle+voice) menu ack."""
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def _char(name):
    c = CharacterClass()
    c.SetCharacterName(name)
    return c


def test_ack_none_character_is_noop():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.acknowledge(None)  # must not raise
    assert _subtitle()._snapshot(now=0.0) is None


def test_ack_falls_back_to_aye_captain_when_no_line(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)
    char = _char("Tactical")  # no YesSir, no database -> fallback
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Aye, Captain."


def test_ack_sirN_path_uses_character_database(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)  # -> "Sir1"
    char = _char("Helm")
    char.SetDatabase(TGLocalizationDatabase("x.tgl", strings={"HelmSir1": "Aye, sir."}))
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Aye, sir."


def test_ack_yessir_path_uses_mission_database(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("m.tgl", strings={"FelixYes": "On it, Captain."})
    monkeypatch.setattr(crew_speech, "_mission_database", lambda: db)
    char = _char("Tactical")
    char.SetYesSir("FelixYes")
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speech"] == "On it, Captain."


def test_ack_yessir_falls_back_when_mission_db_unavailable(monkeypatch):
    # YesSir set but the mission DB can't be loaded -> the fallback still
    # guarantees a visible subtitle.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    monkeypatch.setattr(crew_speech, "_mission_database", lambda: None)
    char = _char("Tactical")
    char.SetYesSir("FelixYes")
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Aye, Captain."
