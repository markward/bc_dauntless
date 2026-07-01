"""_live_speech_characters must enumerate BOTH player-bridge officers and
comm-set characters, so lip-sync can resolve a hailing comm speaker (e.g. Soams
on the viewscreen) by name. Before this, the resolver only saw the "bridge" set,
so comm speakers got subtitles + audio but a frozen mouth.
"""
import App as _App
from engine.appc.sets import SetClass
import engine.host_loop as hl


def _char(name, iid, hidden=0):
    c = _App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleM/BodyMaleM.nif",
        "data/Models/Characters/Heads/HeadMiguel/miguel_head.nif",
    )
    c.SetCharacterName(name)
    c._render_instance = iid
    c.SetHidden(hidden)
    return c


class _Controller:
    def __init__(self, comm_set_ids):
        self.comm_set_ids = comm_set_ids


def test_includes_bridge_and_comm_characters():
    _App.g_kSetManager._sets.clear()

    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(_char("Picard", 1), "Picard")
    _App.g_kSetManager.AddSet(bridge, "bridge")

    comm = SetClass(); comm.SetName("MiscEng")
    comm.AddObjectToSet(_char("Soams", 9), "Soams")
    _App.g_kSetManager.AddSet(comm, "MiscEng")

    names = {getattr(c, "_character_name", None)
             for c in hl._live_speech_characters(_Controller({"MiscEng": 5}))}
    assert "Picard" in names          # player-bridge officer
    assert "Soams" in names           # comm-set character (the fix)


def test_comm_character_included_even_when_hidden():
    # Comm characters are assembled while hidden and un-hidden for the hail; the
    # resolver includes any comm char that carries a render instance so lip-sync
    # can drive the named speaker regardless of a momentary hidden state.
    _App.g_kSetManager._sets.clear()
    comm = SetClass(); comm.SetName("MiscEng")
    comm.AddObjectToSet(_char("Soams", 9, hidden=1), "Soams")
    _App.g_kSetManager.AddSet(comm, "MiscEng")

    names = {getattr(c, "_character_name", None)
             for c in hl._live_speech_characters(_Controller({"MiscEng": 5}))}
    assert "Soams" in names


def test_comm_character_without_instance_excluded():
    # A comm character not yet realised (no render instance) is skipped.
    _App.g_kSetManager._sets.clear()
    comm = SetClass(); comm.SetName("MiscEng")
    ghost = _char("Ghost", 0)
    ghost._render_instance = None
    comm.AddObjectToSet(ghost, "Ghost")
    _App.g_kSetManager.AddSet(comm, "MiscEng")

    names = {getattr(c, "_character_name", None)
             for c in hl._live_speech_characters(_Controller({"MiscEng": 5}))}
    assert "Ghost" not in names


def test_no_comm_sets_returns_bridge_only():
    _App.g_kSetManager._sets.clear()
    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(_char("Picard", 1), "Picard")
    _App.g_kSetManager.AddSet(bridge, "bridge")

    names = {getattr(c, "_character_name", None)
             for c in hl._live_speech_characters(_Controller({}))}
    assert names == {"Picard"}
