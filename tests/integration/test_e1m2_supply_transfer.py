"""E1M2's supply-transfer conversation plays to the end whatever the
shield state.

With shields up, E1M2.CheckShields plays Brex's "Lowering shields" plus
Actions.ShipScriptActions.FlickerShields, which walks the player's
ShieldsDisplay panes (GetNthChild DISPLAY_PANE -> TOP/BOTTOM_PANE). Our
ShieldsDisplay had no pane tree, FlickerShields raised AttributeError, the
CheckShields completion event never posted, and the conversation stalled
before E1M2TransferSupplies3 -- taking 4, 5, 6 and E2M0Briefing with it.
Live-reported 2026-10-07.
"""
import App
import pytest

from tests.helpers import headless_mission as hm

_REST = ["E1M2TransferSupplies3", "E1M2TransferSupplies4",
         "E1M2TransferSupplies5", "E1M2TransferSupplies6"]


@pytest.mark.parametrize("shields_up", [False, True])
def test_supply_conversation_plays_to_the_end(monkeypatch, shields_up):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    import Maelstrom.Episode1.E1M2.E1M2 as m
    from engine.appc import crew_speech
    spoken = []
    real_emit = crew_speech.emit

    def spy(speaker, db, line_id, priority, lips=True):
        spoken.append(str(line_id))
        return real_emit(speaker, db, line_id, priority, lips=lips)

    monkeypatch.setattr(crew_speech, "emit", spy)
    player = App.Game_GetCurrentPlayer()
    player.SetAlertLevel(player.YELLOW_ALERT if shields_up else player.GREEN_ALERT)
    hm.tick(1.0)
    assert bool(player.GetShields().IsOn()) is shields_up

    # The state OrbitingHaven leaves once the win has been called and the
    # player reaches orbit (E1M2.py:2283).
    m.g_bMissionTerminate = 1
    m.g_bSuppliesTransfered = m.FALSE
    m.g_bSequenceRunning = m.FALSE
    m.g_bCanTransferSupplies = m.TRUE
    spoken.clear()
    m.TransferSupplies(None)
    hm.tick(180.0)

    assert [k for k in spoken if k in _REST] == _REST
    if shields_up:
        assert "LoweringShields" in spoken


_REINSERTED = ["E1M2TransferSupplies1", "E1M2TransferSupplies2",
               "E1M2TransferSupplies2a",
               "E1M2TransferSupplies3", "E1M2TransferSupplies3a",
               "E1M2TransferSupplies3b",
               "E1M2TransferSupplies4", "E1M2TransferSupplies4a",
               "E1M2TransferSupplies5", "E1M2TransferSupplies6"]


def _supply_lines(spoken):
    return [k for k in spoken if k.startswith("E1M2TransferSupplies")]


def _spy(monkeypatch):
    from engine.appc import crew_speech
    spoken = []
    real_emit = crew_speech.emit

    def spy(speaker, db, line_id, priority, lips=True):
        spoken.append(str(line_id))
        return real_emit(speaker, db, line_id, priority, lips=lips)

    monkeypatch.setattr(crew_speech, "emit", spy)
    return spoken


def test_transfer_supplies_speaks_the_reinserted_replicator_lines(monkeypatch):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    import Maelstrom.Episode1.E1M2.E1M2 as m
    spoken = _spy(monkeypatch)
    m.g_bMissionTerminate = 1
    m.g_bSuppliesTransfered = m.FALSE
    m.g_bSequenceRunning = m.FALSE
    m.g_bCanTransferSupplies = m.TRUE
    m.TransferSupplies(None)
    hm.tick(240.0)
    assert _supply_lines(spoken) == _REINSERTED


def test_win_with_transfer_speaks_the_reinserted_replicator_lines(monkeypatch):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    import Maelstrom.Episode1.E1M2.E1M2 as m
    spoken = _spy(monkeypatch)
    m.g_bMissionTerminate = 1
    m.g_bSuppliesTransfered = m.FALSE
    m.WinWithTransfer()
    hm.tick(240.0)
    assert _supply_lines(spoken) == _REINSERTED
    # BC's unconditional "Lowering shields" follows 2a in this branch.
    assert spoken.index("LoweringShields") == spoken.index("E1M2TransferSupplies2a") + 1
