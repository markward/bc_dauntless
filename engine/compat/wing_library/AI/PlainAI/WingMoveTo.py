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

With member.slot = (target_name, body_dir, standoff_gu) and that target alive
in the ship's set, the point is the slot, re-read from the target's live pose
each Update: target position + R * body_dir * standoff (R's columns are
right/forward/up). A target that is gone falls back to move_point.

Holding the slot (final review I3): within _SLOW_GU of it the ship enters
hold mode (member.slot_hold), and leaves it only past _LEAVE_GU. Holding,
it turns to face the target and thrusts only by the slot offset along its
nose, clamp(dot(forward, slot - here) / _SLOW_GU, 0, 1): nothing when the
slot is behind or beside it. (Turning to the target while thrusting by the
distance drove it on toward the target and through the slot.) Outside hold
mode it flies at the slot point as above.
"""
import math

import App

_SLOW_GU = 20.0
_STOP_GU = 2.0
_LEAVE_GU = 40.0


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

    def _Hold(self, member, fDistance):
        """Hold mode with hysteresis: in within _SLOW_GU, out past
        _LEAVE_GU."""
        if member.slot_hold:
            member.slot_hold = fDistance <= _LEAVE_GU
        else:
            member.slot_hold = fDistance <= _SLOW_GU
        return member.slot_hold

    def _SlotTarget(self, pShip, sName):
        pSet = pShip.GetContainingSet()
        if pSet is None:
            return None
        pTarget = App.ShipClass_GetObject(pSet, sName)
        from engine.wings import brain
        if not brain._alive(pTarget):
            return None
        return pTarget

    def Update(self):
        pShip = self.pCodeAI.GetShip()
        if pShip is None:
            return App.ArtificialIntelligence.US_ACTIVE
        from engine.wings import roster
        member = roster.member(pShip.GetName())
        if member is None:
            return App.ArtificialIntelligence.US_DONE
        point = member.move_point
        vFace = None
        slot = member.slot
        if slot is not None:
            pTarget = self._SlotTarget(pShip, slot[0])
            if pTarget is not None:
                from engine.wings import attack
                R = pTarget.GetWorldRotation()
                vT = pTarget.GetWorldLocation()
                point = attack.slot_point(
                    (vT.x, vT.y, vT.z),
                    [(c.x, c.y, c.z) for c in
                     (R.GetCol(0), R.GetCol(1), R.GetCol(2))],
                    slot[1], slot[2])
                vFace = vT
        if point is None:
            self._Impulse(pShip, 0.0)
            return App.ArtificialIntelligence.US_ACTIVE
        vHere = pShip.GetWorldLocation()
        fDistance = math.sqrt((point[0] - vHere.x) ** 2
                              + (point[1] - vHere.y) ** 2
                              + (point[2] - vHere.z) ** 2)
        if vFace is not None and self._Hold(member, fDistance):
            pShip.TurnTowardLocation(vFace)
            vFwd = pShip.GetWorldRotation().GetCol(1)
            fAhead = (vFwd.x * (point[0] - vHere.x)
                      + vFwd.y * (point[1] - vHere.y)
                      + vFwd.z * (point[2] - vHere.z))
            self._Impulse(pShip, min(1.0, max(0.0, fAhead / _SLOW_GU)))
            return App.ArtificialIntelligence.US_ACTIVE
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
