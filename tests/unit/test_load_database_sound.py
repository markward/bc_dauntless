"""TGSoundManager.LoadDatabaseSoundInGroup: TGL key -> wav resolve + register.

Hermetic: tests use a fresh TGSoundManager() (not .instance()) so the
conftest-persisted singleton state never leaks in or out. The one test that
must exercise the singleton (SetGroup resolves TGSoundManager.instance()) uses
a unique LDBS_* name. No audio backend in tests, so a real wav never loads —
LoadSoundInGroup's register-unloaded contract is what we assert against.
"""
from engine.audio.tg_sound import TGSoundManager, TGSound
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    # A real localization DB; `sounds` maps key -> wav filename, exactly what
    # GetFilename returns. Missing keys return "".
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_registers_under_sound_name_and_tags_group():
    mgr = TGSoundManager()
    db = _db({"Shields05": "sound/Test/Shields05.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "Shields05", "Bridge")
    # Registered under the SOUND NAME (the key), not the filename.
    assert mgr.GetSound("Shields05") is snd
    assert mgr.GetSound("sound/Test/Shields05.wav") is None
    # Group tag is set on the sound and in the manager's group set.
    assert snd.GetGroup() == "Bridge"
    assert "Shields05" in mgr._groups.get("Bridge", set())


def test_missing_key_returns_none_and_registers_nothing():
    mgr = TGSoundManager()
    db = _db({})  # key absent -> GetFilename returns ""
    assert mgr.LoadDatabaseSoundInGroup(db, "NoSuchKey", "Bridge") is None
    assert mgr.GetSound("NoSuchKey") is None


def test_none_db_returns_none():
    mgr = TGSoundManager()
    assert mgr.LoadDatabaseSoundInGroup(None, "AnyName", "Bridge") is None
    assert mgr.GetSound("AnyName") is None


def test_blank_name_returns_none():
    mgr = TGSoundManager()
    db = _db({"": "sound/empty.wav"})
    assert mgr.LoadDatabaseSoundInGroup(db, "", "Bridge") is None


def test_flags_arg_accepted_and_ignored():
    mgr = TGSoundManager()
    db = _db({"Line1": "sound/Line1.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "Line1", "LoadedOnDemand", TGSound.LS_STREAMED)
    assert mgr.GetSound("Line1") is snd


def test_setgroup_moves_between_group_sets():
    # SetGroup operates on TGSoundManager.instance(); load into it so the sound
    # and its SetGroup target the same manager. Unique name avoids cross-test
    # leakage in the persisted singleton.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_MoveMe": "sound/LDBS_MoveMe.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "LDBS_MoveMe", "")
    assert snd.GetGroup() == ""
    snd.SetGroup("Maelstrom.M1Basic")
    assert snd.GetGroup() == "Maelstrom.M1Basic"
    assert "LDBS_MoveMe" in mgr._groups.get("Maelstrom.M1Basic", set())
    assert "LDBS_MoveMe" not in mgr._groups.get("", set())
