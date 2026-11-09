"""AI.PlainAI.WingRejoin -- fly back to the wing's current commander.

Served by the claimed-namespace rule (engine/compat/claimed.py); spec
2026-11-09-wing-leaders-phase-a-design.md §7, §11.

    pRejoin = App.PlainAI_Create(pShip, "WingRejoin")
    pRejoin.SetScriptModule("WingRejoin")

The stock FollowObject manoeuvre (AI/PlainAI/FollowObject.py, its default
rough distances), aimed at the commander of the ship's wing. The commander
is read from the wing on every Update, so a handover retargets the
manoeuvre with no tree surgery -- and a SetTarget broadcast (SelectTarget
calls SetTarget on every AI in the tree, which FollowObject maps to
SetFollowObjectName) never leaves it following an enemy.

* No wing, or a leaderless wing (no commander): US_DONE, as FollowObject
  reports when it has nothing to follow. Leaderless is permanent, so is DONE.
* A commander not in this ship's set (it died and was removed, or warped)
  holds US_ACTIVE without moving, rather than FollowObject's US_DONE: a
  PlainAI that returns DONE is latched for good, and the brain hands over
  (or clears the rejoin flag) on its next tick.
"""
import App
import AI.PlainAI.FollowObject

_FollowObject = AI.PlainAI.FollowObject.FollowObject


class WingRejoin(_FollowObject):
    def __init__(self, pCodeAI):
        _FollowObject.__init__(self, pCodeAI)
        # FollowObject's one required parameter. The ship's own name stands
        # in when there is no commander yet; Update re-reads it anyway.
        self.SetFollowObjectName(self.GetCommanderName() or self._OwnName())

    def _OwnName(self):
        pShip = self.pCodeAI.GetShip()
        return pShip.GetName() if pShip is not None else ""

    def GetCommanderName(self):
        from engine.wings import roster
        wing = roster.wing_of(self._OwnName())
        if wing is None or wing.leaderless:
            return None
        return wing.commander

    def Update(self):
        sCommander = self.GetCommanderName()
        if sCommander is None:
            return App.ArtificialIntelligence.US_DONE
        self.SetFollowObjectName(sCommander)
        pShip = self.pCodeAI.GetShip()
        pSet = pShip.GetContainingSet() if pShip is not None else None
        if pSet is not None and App.ObjectClass_GetObject(pSet, sCommander) is None:
            return App.ArtificialIntelligence.US_ACTIVE
        return _FollowObject.Update(self)
