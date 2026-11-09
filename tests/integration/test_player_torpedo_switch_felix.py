"""Felix around the player's torpedo-type switch.

The player's switch (weapon_config.cycle_torpedo_type -> TorpedoSystem.
CycleAmmoType) now empties every tube, as in the original
(tests/oracle/test_projectiles.py T6). These check what the SDK's tactical
officer says around it (Bridge/TacticalCharacterHandlers.py, registered on the
player by AttachMenuToTactical):

- PlayerTorpChanged (ET_PLAYER_TORPEDO_TYPE_CHANGED): one "LoadingPhoton" /
  "LoadingQuantum" line per switch;
- PlayerCantFire (ET_CANT_FIRE): firing a type whose count is 0 says
  "OutOfPhotons" / "OutOfQuantums" (skipped within 10 s of Felix's last
  line). Dauntless posts ET_CANT_FIRE only for an empty magazine; whether
  the original also posts it while the tubes reload after a switch (Felix's
  "gt037", not reloaded yet) is unmeasured: the human-run capture doesn't
  log ET_CANT_FIRE.
"""
import pytest

import App
from engine.appc import weapon_config
from engine.appc.weapon_subsystems import TorpedoAmmoType
from tests.helpers import headless_mission

E1M2 = "Maelstrom.Episode1.E1M2.E1M2"


@pytest.fixture
def player():
    headless_mission.load(E1M2)
    top = App.TopWindow_GetTopWindow()
    if top.IsCutsceneMode():
        top.EndCutscene()
    p = App.Game_GetCurrentPlayer()
    assert p is not None
    return p


@pytest.fixture
def lines(monkeypatch):
    said = []
    real = App.CharacterAction_Create

    def action(who, kind, line=None, *a, **k):
        if kind == App.CharacterAction.AT_SAY_LINE and line is not None:
            said.append(str(line))
        return real(who, kind, line, *a, **k)

    monkeypatch.setattr(App, "CharacterAction_Create", action)
    return said


def _with_quantums(player, count=20):
    """E1M2's Galaxy carries photons only: give it a second, stocked type so
    the switch has somewhere to go."""
    ts = player.GetTorpedoSystem()
    if ts.GetNumAmmoTypes() < 2:
        q = TorpedoAmmoType("Quantum", max_torpedoes=count)
        q.SetAvailable(count)
        ts.AddAmmoType(q)
    return ts


def _quiet_felix():
    """Felix's last line long ago, so PlayerCantFire's 10 s rule
    (GetLastTalkTime, kept by crew_speech) doesn't swallow the line under
    test."""
    from engine.appc import crew_speech
    felix = App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"), "Tactical")
    assert felix is not None, "no tactical officer on the bridge"
    crew_speech.bus()._last_talk[str(felix._character_name)] = (
        App.g_kUtopiaModule.GetGameTime() - 100.0)
    assert App.g_kUtopiaModule.GetGameTime() - felix.GetLastTalkTime() >= 10.0
    return felix


def test_a_switch_has_felix_say_one_loading_line(player, lines):
    ts = _with_quantums(player)
    weapon_config.cycle_torpedo_type(player)
    assert ts.GetCurrentAmmoType().GetAmmoName() == "Quantum"
    loading = [l for l in lines if l.startswith("Loading") or l == "PhotonsOnlyDaunt"]
    assert loading == ["LoadingQuantum"]
    weapon_config.cycle_torpedo_type(player)
    loading = [l for l in lines if l.startswith("Loading") or l == "PhotonsOnlyDaunt"]
    assert loading == ["LoadingQuantum", "LoadingPhoton"]


def test_out_of_quantums_still_plays_after_a_switch(player, lines):
    ts = _with_quantums(player)
    weapon_config.cycle_torpedo_type(player)
    ts.GetCurrentAmmoType().SetAvailable(0)
    _quiet_felix()
    del lines[:]
    ts.StartFiring(None)
    assert "OutOfQuantums" in lines
