"""E2M0's WarbirdsWarpOut builds the Warbirds' retreat and asks the
Engineering repair pane whether anything is being repaired:
TGPane_Cast(EngRepairPane_GetRepairPane().GetNthChild(REPAIR_AREA))
.GetNumChildren(). EngRepairPane_GetRepairPane fell to the stub, the cast
gave None and the call raised AFTER the mission had reset the Warbirds' and
Klingons' AI and latched g_bWarbirdsWarpCalled, so the fight stopped dead
and the retreat never ran (user report 2026-11-03)."""
import App

from tests.helpers import headless_mission

E2M0 = "Maelstrom.Episode2.E2M0.E2M0"


def test_the_repair_pane_areas_answer_with_the_repair_queue():
    headless_mission.load(E2M0)
    pane = App.EngRepairPane_GetRepairPane()
    for slot in ("REPAIR_AREA", "WAITING_AREA", "DESTROYED_AREA"):
        area = App.TGPane_Cast(pane.GetNthChild(getattr(App.EngRepairPane, slot)))
        assert area is not None, slot
        assert area.GetNumChildren() == 0, slot      # nothing damaged yet

    player = App.Game_GetCurrentPlayer()
    sensors = player.GetSensorSubsystem()
    player.DamageSystem(sensors, sensors.GetCondition() * 0.5)
    from engine.core.loop import GameLoop
    loop = GameLoop()
    for _ in range(5):
        loop.tick()
    area = App.TGPane_Cast(pane.GetNthChild(App.EngRepairPane.REPAIR_AREA))
    assert area.GetNumChildren() == 1


def test_warbirds_warp_out_queues_the_retreat():
    headless_mission.load(E2M0)
    import sys
    mod = sys.modules[E2M0]
    mod.g_bMissionLost = 0
    mod.g_bWarbirdsWarpCalled = 0
    queued = []
    import MissionLib
    orig = MissionLib.QueueActionToPlay
    MissionLib.QueueActionToPlay = lambda a: queued.append(a)
    try:
        mod.WarbirdsWarpOut()
    finally:
        MissionLib.QueueActionToPlay = orig
    assert len(queued) == 1
