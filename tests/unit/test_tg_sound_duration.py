"""duration_for returns 0.0 without an audio backend / unloaded sound."""
from engine.audio.tg_sound import TGSoundManager


def test_duration_for_unloaded_is_zero():
    mgr = TGSoundManager.instance()
    assert mgr.duration_for("DefinitelyNotLoadedSfx") == 0.0
