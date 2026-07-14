"""End-to-end proof: the real SDK AI.Preprocessors.FelixReportStatus +
UpdateAIStatus pair collects status through ArtificialIntelligence.GetFocusAIs.

FelixReportStatus.Update (AI/Preprocessors.py:2227-2246) walks
self.pCodeAI.GetFocusAIs() and calls CallExternalFunction("QueryAIStatus",
lStatus) on each focused node. UpdateAIStatus.CodeAISet
(AI/Preprocessors.py:2171-2176) registers that external function when
SetPreprocessingMethod binds it (Task 9). Task 10 supplies GetFocusAIs
itself. This test drives both real SDK classes together (no shim, no mock)
to prove the whole previously-dead path now works, rather than just
asserting the isolated GetFocusAIs unit contract.
"""
import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()


def _build_felix_tree():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass()
    pSet.AddObjectToSet(ours, "Ours")

    from AI.Preprocessors import FelixReportStatus, UpdateAIStatus

    leaf = PlainAI_Create(ours, "leaf")

    pUpdateInst = UpdateAIStatus("AttackStatus_MovingIn")
    pUpdateStatus = PreprocessingAI_Create(ours, "UpdateStatus")
    pUpdateStatus.SetInterruptable(1)
    pUpdateStatus.SetPreprocessingMethod(pUpdateInst, "Update")
    pUpdateStatus.SetContainedAI(leaf)

    pFelixInst = FelixReportStatus()
    pFelixReport = PreprocessingAI_Create(ours, "FelixReport")
    pFelixReport.SetInterruptable(1)
    pFelixReport.SetPreprocessingMethod(pFelixInst, "Update")
    pFelixReport.SetContainedAI(pUpdateStatus)

    return pFelixReport, pFelixInst, pUpdateStatus


def test_update_ai_status_registers_query_ai_status_on_bind():
    """Task 9's generic CodeAISet call: SetPreprocessingMethod binding
    UpdateAIStatus must register the QueryAIStatus external function that
    FelixReportStatus.Update later calls."""
    _reset_app_state()
    _pFelixReport, _pFelixInst, pUpdateStatus = _build_felix_tree()
    assert "QueryAIStatus" in pUpdateStatus._external_functions


def test_felix_collects_status_string_through_get_focus_ais():
    """Drive the real tree through the driver. GetFocusAIs is one tick
    behind the dispatch that sets focus (FelixReportStatus.Update runs
    before its own contained subtree is dispatched this tick), so the
    status string that UpdateAIStatus registered doesn't reach
    FelixReportStatus.sLastStatus until the tick after the UpdateStatus
    node first holds focus. Before GetFocusAIs existed this whole call
    raised AttributeError on tick 1."""
    _reset_app_state()
    pFelixReport, pFelixInst, pUpdateStatus = _build_felix_tree()

    # Tick 1: pUpdateStatus is reached (gains focus) for the first time,
    # but FelixReportStatus.Update() (which runs before contained dispatch)
    # can't see it yet -- GetFocusAIs() only returns pFelixReport itself.
    tick_ai(pFelixReport, game_time=0.0)
    assert pFelixInst.sLastStatus is None
    assert pUpdateStatus.HasFocus()

    # Tick 2: pUpdateStatus still holds focus from tick 1 (focus latches
    # persist until LostFocus), so it's now on the GetFocusAIs() path
    # FelixReportStatus.Update walks -- its registered QueryAIStatus
    # external function appends the status string.
    tick_ai(pFelixReport, game_time=1.0)
    assert pFelixInst.sLastStatus == "AttackStatus_MovingIn"


def test_get_focus_ais_from_root_includes_the_whole_focused_chain():
    """Direct proof against the method under test: after the tree has
    ticked once, GetFocusAIs() called from the root returns every node
    on the active focus path in tree order."""
    _reset_app_state()
    pFelixReport, _pFelixInst, pUpdateStatus = _build_felix_tree()

    tick_ai(pFelixReport, game_time=0.0)

    focus_ais = pFelixReport.GetFocusAIs()
    assert pFelixReport in focus_ais
    assert pUpdateStatus in focus_ais
    assert focus_ais.index(pFelixReport) < focus_ais.index(pUpdateStatus)
