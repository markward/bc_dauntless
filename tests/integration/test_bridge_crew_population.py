"""End-to-end: populated crew -> resolve_character -> acknowledge resolves a
real per-officer line (not the 'Aye, Captain.' fallback)."""
import pytest

import App
import LoadBridge
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase
from engine.ui import crew_menu_hotkeys


def _fresh_bridge_set():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    pSet.CreateAmbientLight(1.0, 1.0, 1.0, 1.0, "ambientlight1")
    return pSet


@pytest.fixture(autouse=True)
def _cleanup_bridge_set():
    """Restore set-manager + crew-populated flag after each test so downstream
    tests that rely on an unpopulated bridge set are not affected."""
    yield
    App.g_kSetManager._sets.clear()
    LoadBridge._reset_crew_populated()


def test_resolve_character_returns_populated_officer():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    char = crew_menu_hotkeys.resolve_character("Tactical")
    assert isinstance(char, CharacterClass)
    assert char.GetCharacterName() == "Felix"


def test_acknowledge_resolves_real_line_for_populated_officer(monkeypatch):
    # Distinct line text (not the "Aye, Captain." fallback) so the assertion
    # can only pass if the line was resolved from the populated officer's DB.
    LoadBridge._reset_crew_populated()
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    felix = crew_menu_hotkeys.resolve_character("Tactical")
    # Pin the ack line deterministically (rand -> "FelixSir1") and give Felix a
    # DB that has it, so the test does not depend on the game/ TGL being present.
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)
    felix.SetDatabase(TGLocalizationDatabase("crew.tgl", strings={"FelixSir1": "Phasers ready, sir."}))

    crew_speech.acknowledge(felix)

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap["speaker"] == "Felix"
    assert snap["speech"] == "Phasers ready, sir."   # real DB line, not the fallback
