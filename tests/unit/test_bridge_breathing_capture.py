import App
from engine.appc.bridge_placement import capture_breathing


def _char(location, breathe_entry=None):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    if breathe_entry is not None:
        c.AddAnimation(*breathe_entry)
    return c


def test_standing_station_resolves_standing_console():
    c = _char("DBEngineer",
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    p = capture_breathing(c)
    assert p == {"clip_nif": "data/animations/standing_console.NIF"}


def test_seated_station_resolves_seated_clip():
    c = _char("DBHelm",
              ("DBHelmBreathe", "Bridge.Characters.CommonAnimations.SeatedM"))
    p = capture_breathing(c)
    assert p == {"clip_nif": "data/animations/seated_M.nif"}


def test_no_breathe_registration_returns_none():
    c = _char("DBEngineer")          # location set, but no <loc>Breathe entry
    assert capture_breathing(c) is None


def test_no_location_returns_none():
    c = _char(None,
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    assert capture_breathing(c) is None
