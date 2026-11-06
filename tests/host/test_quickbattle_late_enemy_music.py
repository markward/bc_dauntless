"""An enemy that joins a Quick Battle after it started brings in the combat music.

Late groups (engine/quickbattle/late_arrivals.py) and stations turned hostile
(engine/systems/station_hostility.py) add their names to the mission's enemy
group mid-battle, after DynamicMusic's "enemies within 400" ConditionInRange
was rebuilt at the start (ET_SET_PLAYER). Without ET_OBJECT_GROUP_CHANGED the
condition never saw them and the music stayed on "Starting Ambient" through
the fight (user report 2026-11-06)."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader


def test_a_late_enemy_starts_the_combat_music(monkeypatch):
    import App, DynamicMusic, loadspacehelper
    import QuickBattle.QuickBattle as QB
    from engine.core.loop import GameLoop
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    QB.g_kEnemyList = [("Sovereign", "Sovereign", "msg", "QuickBattle.QuickBattleAI", "Enemy", 1.0)]
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    player = App.Game_GetCurrentPlayer()
    pset = player.GetContainingSet()
    p = player.GetWorldLocation()
    for o in pset.GetClassObjectList(App.CT_SHIP):          # the first enemy: far off, idle
        s = App.ShipClass_Cast(o)
        if s is not None and s.GetName() != player.GetName():
            s.ClearAI()
            s.SetTranslateXYZ(p.x, p.y + 5000.0, p.z)
    loop = GameLoop()
    for _ in range(60):
        loop.tick()
    assert not DynamicMusic.pStateMachine.GetMusicState().startswith("Combat")
    late = loadspacehelper.CreateShip("Galor", pset, "Late Galor", None)   # what late_arrivals does
    late.SetTranslateXYZ(p.x + 100.0, p.y, p.z)
    QB.pEnemies.AddName(late.GetName())
    for _ in range(60):
        loop.tick()
    assert DynamicMusic.pStateMachine.GetMusicState().startswith("Combat")
