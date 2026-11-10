"""Conditions.ConditionWing -- a condition the wing brain pushes.

Served by the claimed-namespace rule (engine/compat/claimed.py); spec
2026-11-09-wing-leaders-phase-a-design.md §11.

    App.ConditionScript_Create("Conditions.ConditionWing", "ConditionWing",
                               sShipName, sKind)

sKind is "rejoin", "ram", "flee", "withdraw", "guard" or "fallback". The
condition starts false and holds no logic of its own: on construction it
registers with the ship's wing member record (engine.wings.roster), and the
wing brain sets its status to 1 or 0 when that member should (or should no
longer) do that. A ship that is not a wing member registers nothing and
stays false.
"""


class ConditionWing:
    def __init__(self, pCodeCondition, sShip, sKind):
        self.pCodeCondition = pCodeCondition
        self.sShip = sShip
        self.sKind = sKind
        pCodeCondition.SetStatus(0)
        from engine.wings import roster
        member = roster.member(sShip)
        if member is not None:
            member.conditions[sKind] = pCodeCondition
