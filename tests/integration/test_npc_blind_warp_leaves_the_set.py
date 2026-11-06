"""An NPC's destination-less warp (AI Warp, WarpBlindly...) takes it out of
its set, as BC's WarpSequence.SetupSequence does (flash, HideShip, "Place the
ship in the warp set" regardless of destination), so ET_EXITED_SET fires.
E2M0 waits on that for both retreating Warbirds before its story moves on;
Dauntless's blind warp was a no-op and the mission stalled (user report
2026-11-03)."""
import sys

import App

from tests.helpers import headless_mission

E2M0 = "Maelstrom.Episode2.E2M0.E2M0"


def test_retreating_warbird_leaves_tevron2_and_e2m0_hears_it(monkeypatch):
    headless_mission.load(E2M0)
    import loadspacehelper
    mod = sys.modules[E2M0]
    left = []
    monkeypatch.setattr(mod, "WarbirdsLeft", lambda *a: left.append(1))
    mod.g_lEnemyShips = ["Warbird 1"]
    pSet = App.g_kSetManager.GetSet("Tevron2")
    warbird = loadspacehelper.CreateShip("E2M0Warbird", pSet, "Warbird 1", "Warbird1Start")
    from Maelstrom.Episode2.E2M0 import E2M0_AI_WarbirdWarp
    warbird.SetAI(E2M0_AI_WarbirdWarp.CreateAI(warbird))
    from engine.core.loop import GameLoop
    loop = GameLoop()
    for _ in range(60 * 40):
        loop.tick()
        if left:
            break
    assert pSet.GetObject("Warbird 1") is None
    assert left == [1]


def test_the_players_blind_warp_stays_put():
    headless_mission.load(E2M0)
    player = App.Game_GetCurrentPlayer()
    home = player.GetContainingSet()
    seq = App.WarpSequence_Create(player, None, 3.0, None)
    seq.Play()
    from engine.core.loop import GameLoop
    loop = GameLoop()
    for _ in range(60 * 5):
        loop.tick()
    assert player.GetContainingSet() is home
