"""An edit to the enemy group mid-fight leaves the combat music alone.

Every ET_OBJECT_GROUP_CHANGED of the enemy group runs ConditionInRange.SetObjects,
which sets the condition to 0 and rebuilds the proximity check, adding back
each enemy already inside 400 GU (SetupProximitySphere measures the distance
itself). BC's event queue delivers the condition events after that, so
DynamicMusic reads 1 and nothing changes. Posted at once, it read the passing
0: Starting Ambient, then a new combat track, on every edit (escape pods,
late arrivals, a station turning hostile)."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_end_of_fight_music import _fight


def test_an_enemy_group_edit_mid_fight_keeps_the_combat_music(monkeypatch):
    import QuickBattle.QuickBattle as QB
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    sm = DM.pStateMachine
    state, playing = sm.GetMusicState(), DM.sCurrentMusicType
    seen = []
    orig = sm.EvaluateMusicState

    def evaluate():
        seen.append(sm.pEnemiesInRange.GetStatus())
        return orig()
    monkeypatch.setattr(sm, "EvaluateMusicState", evaluate)
    t = App.g_kUtopiaModule.GetGameTime()
    QB.pEnemies.AddName("Escape Pod 1")
    frames.run(3.0)
    QB.pEnemies.RemoveName("Escape Pod 1")
    frames.run(3.0)
    assert seen and set(seen) == {1}
    assert [e for e in log if e[0] == "SwitchMusic" and e[1] >= t] == []
    assert sm.GetMusicState() == state and DM.sCurrentMusicType == playing
    assert sm.pEnemiesInRange.GetStatus() == 1
