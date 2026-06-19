import App
from engine.appc.bridge_placement import capture_registered_clip, capture_breathing


def _char(location, *anim_entries):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    for e in anim_entries:
        c.AddAnimation(*e)
    return c


def test_resolves_turn_captain_suffix():
    c = _char("DBEngineer",
              ("DBEngineerTurnCaptain", "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain"))
    assert capture_registered_clip(c, "TurnCaptain") == {"clip_nif": "data/animations/db_face_capt_e.nif"}


def test_resolves_breathe_turned_suffix():
    c = _char("DBEngineer",
              ("DBEngineerBreatheTurned", "Bridge.Characters.CommonAnimations.BreathingTurned"))
    assert capture_registered_clip(c, "BreatheTurned") == {"clip_nif": "data/animations/breathing.NIF"}


def test_unregistered_suffix_returns_none():
    c = _char("DBEngineer")
    assert capture_registered_clip(c, "TurnCaptain") is None


def test_no_location_returns_none():
    c = _char(None, ("DBEngineerTurnCaptain", "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain"))
    assert capture_registered_clip(c, "TurnCaptain") is None


def test_capture_breathing_still_works():
    c = _char("DBEngineer",
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    assert capture_breathing(c) == {"clip_nif": "data/animations/standing_console.NIF"}
