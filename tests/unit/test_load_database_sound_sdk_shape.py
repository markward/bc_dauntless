"""Reproduce the exact shipped SDK call patterns against our engine surface,
so a future contract drift on these methods fails a test rather than going
silently mute in-game.
"""
import App
from engine.audio.tg_sound import TGSoundManager, TGSound
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_missionlib_lazy_loader_gate_reaches_sound_action():
    # MissionLib.py:665-681 shape: GetSound miss -> LoadDatabaseSoundInGroup ->
    # GetSound now hits -> build a TGSoundAction on the name.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_Lazy": "sound/LDBS_Lazy.wav"})
    pcString = "LDBS_Lazy"

    assert mgr.GetSound(pcString) is None            # first gate: not loaded
    pGame = App.Game()
    pGame.LoadDatabaseSoundInGroup(db, pcString, "LoadedOnDemand", 0)
    assert mgr.GetSound(pcString) is not None         # second gate: now loaded

    pSound = App.TGSoundAction_Create(pcString, 0)
    assert pSound.GetName() == pcString               # sequence build proceeds


def test_preload_post_load_block_retags_untagged_sound():
    # MissionLib.PreloadMissionLine tail: after LoadDatabaseSound, the sound is
    # set single-shot and, if untagged, filed under the mission script group.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_Preload": "sound/LDBS_Preload.wav"})
    snd = App.Game().LoadDatabaseSound(db, "LDBS_Preload")  # Game -> group ""

    pSound = mgr.GetSound("LDBS_Preload")
    assert pSound is not None
    pSound.SetSingleShot(1)                            # no raise
    if not pSound.GetGroup():                          # exact SDK reassignment
        pSound.SetGroup("Maelstrom.M1Basic")
    assert pSound.GetGroup() == "Maelstrom.M1Basic"
