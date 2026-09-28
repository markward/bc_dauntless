"""The warp button's five action queues (SDK App.py:8723-8738) and the warp
sequence carrying the button's mission/episode (spec §1)."""
import App
from engine.appc.actions import TGAction
from engine.appc.tg_ui.st_widgets import STWarpButton
from engine.appc import warp


def _a():
    return TGAction()


def test_each_queue_keeps_its_actions_in_order():
    b = STWarpButton("Warp")
    a1, a2, a3, a4, a5, a6 = (_a() for _ in range(6))
    b.AddActionBeforeWarp(a1)
    b.AddActionBeforeDuringWarp(a2)
    b.AddActionDuringWarp(a3)
    b.AddActionDuringWarp(a4)
    b.AddActionAfterDuringWarp(a5)
    b.AddActionAfterWarp(a6, 1.5)
    q = b.take_queues()
    assert q["before"] == [(a1, 0.0)]
    assert q["before_during"] == [(a2, 0.0)]
    assert q["during"] == [(a3, 0.0), (a4, 0.0)]
    assert q["after_during"] == [(a5, 0.0)]
    assert q["after"] == [(a6, 1.5)]


def test_take_queues_empties_them():
    b = STWarpButton("Warp")
    b.AddActionDuringWarp(_a())
    b.take_queues()
    assert all(v == [] for v in b.take_queues().values())


def test_clear_bda_sequences_empties_all_five():
    b = STWarpButton("Warp")
    b.AddActionBeforeWarp(_a())
    b.AddActionBeforeDuringWarp(_a())
    b.AddActionDuringWarp(_a())
    b.AddActionAfterDuringWarp(_a())
    b.AddActionAfterWarp(_a())
    b.ClearBDASequences()
    assert all(v == [] for v in b.take_queues().values())


def test_warp_sequence_reports_mission_and_episode():
    ship = App.ShipClass_Create()
    seq = warp.WarpSequence_Create(ship, None, 0.0, "Player Start",
                                   mission="Maelstrom.Episode7.E7M1.E7M1",
                                   episode="Maelstrom.Episode7.Episode7")
    assert seq.GetDestinationMission() == "Maelstrom.Episode7.E7M1.E7M1"
    assert seq.GetDestinationEpisode() == "Maelstrom.Episode7.Episode7"


def test_warp_sequence_mission_defaults_stay_falsy():
    ship = App.ShipClass_Create()
    seq = warp.WarpSequence_Create(ship, None, 0.0, "Player Start")
    assert seq.GetDestinationMission() is None
    assert seq.GetDestinationEpisode() is None
