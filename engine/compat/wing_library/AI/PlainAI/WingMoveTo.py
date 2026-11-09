"""AI.PlainAI.WingMoveTo -- fly to the point the wing brain set.

Served by the claimed-namespace rule (engine/compat/claimed.py); spec
2026-11-09-wing-leaders-phase-b-design.md §6.

    pMove = App.PlainAI_Create(pShip, "WingMoveTo")
    pMove.SetScriptModule("WingMoveTo")

Each Update reads engine.wings.roster member(own name).move_point (a world
(x, y, z) tuple or None). With a point it drives there as the stock
AI/PlainAI/Intercept.py does toward vDestination: TurnTowardLocation, then
SetImpulse along model-forward, the fraction scaling down linearly inside
20 GU and 0 within 2 GU. With no point it stops the ship. It never reports
DONE: the brain owns when the branch ends (its condition goes false).
"""
import App

_SLOW_GU = 20.0
_STOP_GU = 2.0


class WingMoveTo:
    def __init__(self, pCodeAI):
        self.pCodeAI = pCodeAI

    def GetNextUpdateTime(self):
        return 0.0

    def _Impulse(self, pShip, fFraction):
        pShip.SetImpulse(fFraction, App.TGPoint3_GetModelForward(),
                         App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    def Update(self):
        pShip = self.pCodeAI.GetShip()
        if pShip is None:
            return App.ArtificialIntelligence.US_ACTIVE
        from engine.wings import roster
        member = roster.member(pShip.GetName())
        point = member.move_point if member is not None else None
        if point is None:
            self._Impulse(pShip, 0.0)
            return App.ArtificialIntelligence.US_ACTIVE
        vDestination = App.TGPoint3()
        vDestination.SetXYZ(point[0], point[1], point[2])
        vDestination.Subtract(pShip.GetWorldLocation())
        fDistance = vDestination.Length()
        vDestination = App.TGPoint3()
        vDestination.SetXYZ(*point)
        pShip.TurnTowardLocation(vDestination)
        if fDistance <= _STOP_GU:
            fFraction = 0.0
        elif fDistance >= _SLOW_GU:
            fFraction = 1.0
        else:
            fFraction = (fDistance - _STOP_GU) / (_SLOW_GU - _STOP_GU)
        self._Impulse(pShip, fFraction)
        return App.ArtificialIntelligence.US_ACTIVE
