import App
from engine.appc.bridge_placement import capture_placement


def _char(location):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    return c


def test_stand_clip_tactical_holds_frame_zero():
    # TGAnimPosition holds frame 0 (the at-station pose) for the "stand" clips
    # too — holding the last frame left officers frozen stood-up (confirmed
    # in-GUI 2026-06-19).
    p = capture_placement(_char("DBTactical"))
    assert p["clip_nif"] == "data/animations/db_stand_t_l.nif"
    assert p["hidden"] is False
    assert p["sample_at_start"] is True


def test_helm_and_commander_stand_clips():
    assert capture_placement(_char("DBHelm"))["clip_nif"] == "data/animations/db_stand_h_m.nif"
    assert capture_placement(_char("DBCommander"))["clip_nif"] == "data/animations/db_stand_c_m.nif"


def test_movement_clip_science_samples_at_start():
    p = capture_placement(_char("DBScience"))
    assert p["clip_nif"] == "data/animations/db_StoL1_S.nif"
    assert p["sample_at_start"] is True


def test_movement_clip_engineer_samples_at_start():
    p = capture_placement(_char("DBEngineer"))
    assert p["clip_nif"] == "data/animations/db_EtoL1_s.nif"
    assert p["sample_at_start"] is True


def test_ebridge_science_stand_clip_holds_frame_zero():
    # Every placement clip — stand or move-from — holds frame 0 (the at-station
    # pose). EBridge Science's in-place stand clip is no exception.
    p = capture_placement(_char("EBScience"))
    assert p["clip_nif"] == "data/animations/EB_stand_s_s.nif"
    assert p["sample_at_start"] is True


def test_l1_moving_location_is_hidden():
    p = capture_placement(_char("DBL1M"))
    assert p is not None
    assert p["hidden"] is True


def test_empty_location_returns_none():
    assert capture_placement(_char("")) is None


def test_unset_location_returns_none():
    assert capture_placement(_char(None)) is None
