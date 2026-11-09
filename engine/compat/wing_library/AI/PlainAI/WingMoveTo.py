"""AI.PlainAI.WingMoveTo -- fly to the point the wing brain set.

Served by the claimed-namespace rule (engine/compat/claimed.py); spec
2026-11-09-wing-leaders-phase-b-design.md §6.

    pMove = App.PlainAI_Create(pShip, "WingMoveTo")
    pMove.SetScriptModule("WingMoveTo")

Each Update reads engine.wings.roster member(own name).move_point (a world
(x, y, z) tuple or None). With a point it drives there as the stock
AI/PlainAI/Intercept.py does toward vDestination: TurnTowardLocation, then
SetImpulse along model-forward, the fraction scaling down linearly inside
20 GU and 0 within 2 GU. With no point it stops the ship. While the ship is
a wing member it never reports DONE: the brain owns when the branch ends
(its condition goes false). With no member record (the wing was reset) it
reports DONE, as WingRejoin does.
"""
import math

import App

_SLOW_GU = 20.0
_STOP_GU = 2.0


class WingMoveTo:
    def __init__(self, pCodeAI):
        self.pCodeAI = pCodeAI

    def GetNextUpdateTime(self):
        # FollowObject's 0.2 s (WingRejoin inherits it). 0.0 would pin the
        # tree walk's next update to now, so a guarding, falling-back or
        # withdrawing ship would never sleep (AI_MAX_SLEEP_TICKS) and would
        # run this at 60 Hz for a move point the brain changes at 1 Hz. At
        # impulse speeds 0.2 s is under _STOP_GU of travel.
        return 0.2

    def _Impulse(self, pShip, fFraction):
        pShip.SetImpulse(fFraction, App.TGPoint3_GetModelForward(),
                         App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    def Update(self):
        pShip = self.pCodeAI.GetShip()
        if pShip is None:
            return App.ArtificialIntelligence.US_ACTIVE
        from engine.wings import roster
        member = roster.member(pShip.GetName())
        if member is None:
            return App.ArtificialIntelligence.US_DONE
        point = member.move_point
        if point is None:
            self._Impulse(pShip, 0.0)
            return App.ArtificialIntelligence.US_ACTIVE
        vHere = pShip.GetWorldLocation()
        fDistance = math.sqrt((point[0] - vHere.x) ** 2
                              + (point[1] - vHere.y) ** 2
                              + (point[2] - vHere.z) ** 2)
        vDestination = App.TGPoint3()
        vDestination.SetXYZ(point[0], point[1], point[2])
        pShip.TurnTowardLocation(vDestination)
        if fDistance <= _STOP_GU:
            fFraction = 0.0
        elif fDistance >= _SLOW_GU:
            fFraction = 1.0
        else:
            fFraction = (fDistance - _STOP_GU) / (_SLOW_GU - _STOP_GU)
        self._Impulse(pShip, fFraction)
        return App.ArtificialIntelligence.US_ACTIVE
