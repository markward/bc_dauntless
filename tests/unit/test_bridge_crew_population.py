"""LoadBridge.populate_bridge_crew creates the 5 GalaxyBridge officers with
real names + loaded localization DBs. Calls the helper directly (no game-state
guard) for determinism."""
import App
import LoadBridge
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase


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
