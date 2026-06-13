"""LoadBridge.populate_bridge_crew creates the 5 GalaxyBridge officers with
real names + loaded localization DBs."""
import pytest

import App
import LoadBridge
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase
from engine.core.game import Game, _set_current_game


@pytest.fixture(autouse=True)
def _bridge_env():
    # populate_bridge_crew defers without a current game (the SDK
    # CreateCharacter -> LoadSounds path needs one), so set a game for the
    # happy-path tests. Clear set-manager + latch + game after each test so a
    # populated "Tactical"=Felix can't leak into other files (e.g.
    # test_crew_menu_hotkeys expects resolve_character to auto-vivify).
    _set_current_game(Game())
    yield
    App.g_kSetManager._sets.clear()
    LoadBridge._reset_crew_populated()
    _set_current_game(None)


def _fresh_bridge_set():
    # Mirror LoadBridge.Load's set creation enough for CreateCharacter:
    # a "bridge" set with the ambientlight1 the SDK CreateCharacter illuminates.
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    pSet.CreateAmbientLight(1.0, 1.0, 1.0, 1.0, "ambientlight1")
    return pSet


def test_populate_creates_five_named_officers_with_databases():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()

    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    expected = {
        "Tactical": "Felix", "Helm": "Kiska", "XO": "Saffi",
        "Science": "Miguel", "Engineer": "Brex",
    }
    for set_name, char_name in expected.items():
        obj = pSet.GetObject(set_name)
        assert isinstance(obj, CharacterClass), f"{set_name} not a CharacterClass"
        assert obj.GetCharacterName() == char_name
        # SetDatabase("...tgl") (Task 1) must have left a real DB object.
        assert isinstance(obj.GetDatabase(), TGLocalizationDatabase), \
            f"{char_name} has no loaded database"


def test_populate_is_idempotent():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")
    first = pSet.GetObject("Tactical")
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")   # second call
    assert pSet.GetObject("Tactical") is first              # same object, not recreated


def test_populate_unknown_bridge_is_noop():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "NoSuchBridge")   # must not raise
    assert pSet.GetObject("Tactical") is None


def test_populate_defers_without_current_game():
    # The eager pre-game bridge preload (Game_GetCurrentGame() is None) must
    # NOT populate or latch — the SDK CreateCharacter->LoadSounds path needs a
    # game. The mission's own Load() repopulates once the game exists.
    LoadBridge._reset_crew_populated()
    _set_current_game(None)
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")
    assert pSet.GetObject("Tactical") is None
    assert LoadBridge._crew_populated is False   # not latched -> mission Load retries
