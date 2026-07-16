"""SDK-facing delegates route to TGSoundManager and preserve bail semantics.

Delegates resolve TGSoundManager.instance(); tests use unique LDBS_* names to
stay hermetic against the conftest-persisted singleton.
"""
from engine.audio.tg_sound import TGSoundManager, TGSound, TGSound_Create
from engine.core.game import Game, Mission, Episode
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_game_load_database_sound_in_group_registers():
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_G1": "sound/LDBS_G1.wav"})
    snd = Game().LoadDatabaseSoundInGroup(db, "LDBS_G1", "Picard")
    assert mgr.GetSound("LDBS_G1") is snd
    assert snd.GetGroup() == "Picard"


def test_game_load_database_sound_in_group_missing_key_returns_none():
    db = _db({})
    assert Game().LoadDatabaseSoundInGroup(db, "LDBS_G_missing", "Picard") is None


def test_mission_load_database_sound_uses_script_group():
    mgr = TGSoundManager.instance()
    m = Mission()
    m.SetScript("Maelstrom.M1Basic")
    db = _db({"LDBS_M1": "sound/LDBS_M1.wav"})
    snd = m.LoadDatabaseSound(db, "LDBS_M1")
    assert mgr.GetSound("LDBS_M1") is snd
    assert snd.GetGroup() == "Maelstrom.M1Basic"


def test_episode_load_database_sound_registers():
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_E1": "sound/LDBS_E1.wav"})
    snd = Episode().LoadDatabaseSound(db, "LDBS_E1")
    assert mgr.GetSound("LDBS_E1") is snd


def test_tgsound_create_missing_backend_returns_none():
    # No audio backend in tests -> LoadSound returns None, nothing registered.
    assert TGSound_Create("sound/nope.wav", "LDBS_TSC_missing", 0) is None
    assert TGSoundManager.instance().GetSound("LDBS_TSC_missing") is None
