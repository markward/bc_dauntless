"""Focus HANDOVER ordering: when one branch of a tree replaces another in the
same tick, the departing node's LostFocus() must run BEFORE the arriving
node's GotFocus().

BC's dispatcher changes focus at the container, so the pair is ordered by
construction. Our driver discovers departures by set difference and can only
do so once the traversal has finished, so GotFocus is deferred to the end of
the root tick to preserve the order (see ai_driver._flush_pending_got_focus).

The bug this pins, from a live AI-inspector export (a Kessok Light in
QuickBattle): the outer PriorityList carries an SDK `AlertLevel(2)`
preprocessor in BOTH branches. Combat put branch 2 on the path, which saved
`eOldAlertLevel = 0` and raised the alert to 2 (shields up). When branch 1's
gate opened, branch 1's GotFocus read the level as 2 and correctly did
nothing -- and THEN branch 2's LostFocus restored 0. Shields dropped
mid-combat and never came back: AlertLevel.Update is a no-op, so the
surviving node never re-asserts.
"""
from engine.appc.ai import (
    PreprocessingAI, PriorityListAI_Create, ConditionalAI, TGCondition,
    ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass

PS_NORMAL = PreprocessingAI.PS_NORMAL


class _AlertLevel:
    """The SDK's AI/Preprocessors.py:2047 AlertLevel focus hooks, verbatim."""

    def __init__(self, ship, level, restore=1):
        self.ship = ship
        self.eAlertLevel = level
        self.eOldAlertLevel = None
        self.bRestoreOld = restore

    def GotFocus(self):
        self.eOldAlertLevel = self.ship.GetAlertLevel()
        if self.eOldAlertLevel != self.eAlertLevel:
            self.ship.SetAlertLevel(self.eAlertLevel)

    def LostFocus(self):
        if self.bRestoreOld and self.eOldAlertLevel is not None:
            if self.ship.GetAlertLevel() != self.eOldAlertLevel:
                self.ship.SetAlertLevel(self.eOldAlertLevel)

    def Update(self, dEndTime):
        return PS_NORMAL


class _Recorder:
    """Records the global order of focus hooks across every node."""

    def __init__(self, log, name):
        self.log = log
        self.name = name

    def GotFocus(self):
        self.log.append("got:" + self.name)

    def LostFocus(self):
        self.log.append("lost:" + self.name)

    def Update(self, dEndTime):
        return PS_NORMAL


def _gated_branch(ship, name, inst):
    """ConditionalAI(gate) -> PreprocessingAI(inst), the shape of the export's
    "CloakingDisabled" branch."""
    pp = PreprocessingAI(ship, name)
    pp.SetPreprocessingMethod(inst, "Update")
    cond = TGCondition()
    gate = ConditionalAI(ship, name + "Gate")
    gate.AddCondition(cond)
    gate.SetContainedAI(pp)
    return gate, cond


def _two_branch_list(ship, hi_inst, lo_inst):
    hi_gate, hi_cond = _gated_branch(ship, "Hi", hi_inst)
    lo_gate, lo_cond = _gated_branch(ship, "Lo", lo_inst)
    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(hi_gate, 1)
    pl.AddAI(lo_gate, 2)
    return pl, hi_cond, lo_cond


def test_alert_level_survives_priority_handover():
    ship = ShipClass()
    ship.SetAlertLevel(0)
    hi, lo = _AlertLevel(ship, 2), _AlertLevel(ship, 2)
    pl, hi_cond, lo_cond = _two_branch_list(ship, hi, lo)

    # Combat starts on the low-priority branch: alert 0 -> 2, shields up.
    hi_cond.SetStatus(0)
    lo_cond.SetStatus(1)
    tick_ai(pl, 0.0)
    assert ship.GetAlertLevel() == 2
    assert lo.eOldAlertLevel == 0

    # The high-priority gate opens and takes over. Both branches want alert 2,
    # so the level must not move.
    hi_cond.SetStatus(1)
    tick_ai(pl, 1.0)

    assert ship.GetAlertLevel() == 2, (
        "handover between two AlertLevel(2) branches dropped the alert level "
        "to %r -- shields down mid-combat" % ship.GetAlertLevel()
    )


def test_departing_lost_focus_precedes_arriving_got_focus():
    ship = ShipClass()
    log = []
    hi, lo = _Recorder(log, "hi"), _Recorder(log, "lo")
    pl, hi_cond, lo_cond = _two_branch_list(ship, hi, lo)

    hi_cond.SetStatus(0)
    lo_cond.SetStatus(1)
    tick_ai(pl, 0.0)
    assert log == ["got:lo"]

    del log[:]
    hi_cond.SetStatus(1)
    tick_ai(pl, 1.0)

    assert log == ["lost:lo", "got:hi"], (
        "expected the departing node to lose focus before the arriving node "
        "gains it, got %r" % (log,)
    )


def test_got_focus_still_fires_once_per_activation():
    """Deferring GotFocus must not fire it twice, nor re-fire it while the
    node simply stays on the path."""
    ship = ShipClass()
    log = []
    only = _Recorder(log, "only")
    gate, cond = _gated_branch(ship, "Only", only)
    cond.SetStatus(1)

    tick_ai(gate, 0.0)
    tick_ai(gate, 1.0)
    tick_ai(gate, 2.0)

    assert log == ["got:only"]


def test_probed_dormant_priority_child_does_not_gain_focus():
    """A PriorityList child probed and found non-ACTIVE has its focus records
    rolled back (_dispatch_priority_child). The deferred GotFocus queue must be
    rolled back with them, or a rejected child fires GotFocus anyway."""
    ship = ShipClass()
    log = []

    class _Dormant(_Recorder):
        def Update(self, dEndTime):
            return PreprocessingAI.PS_SKIP_DORMANT

    # Added straight to the list, so the PriorityList probes the preprocessor
    # itself and sees a non-ACTIVE status -- the rollback path. (A ConditionalAI
    # wrapper stays ACTIVE regardless of its contained AI, so it never rolls
    # back.)
    hi_pp = PreprocessingAI(ship, "Hi")
    hi_pp.SetPreprocessingMethod(_Dormant(log, "hi"), "Update")
    lo_pp = PreprocessingAI(ship, "Lo")
    lo_pp.SetPreprocessingMethod(_Recorder(log, "lo"), "Update")
    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(hi_pp, 1)
    pl.AddAI(lo_pp, 2)

    # Tick 0 probes hi, finds it dormant and rolls its records back; the list
    # only falls through to lo on the following tick.
    tick_ai(pl, 0.0)
    assert log == [], "a probed-and-rejected priority child gained focus: %r" % (log,)

    tick_ai(pl, 1.0)
    assert "got:hi" not in log, (
        "a probed-and-rejected priority child gained focus: %r" % (log,)
    )
    assert log == ["got:lo"]
