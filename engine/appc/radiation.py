"""Profile radiation: a deliberate departure from BC.

BC's SetupDamage nebula deals ONE hit at creation (bible §15 E1; see
nebula_runtime). The radial profile adds real harm, scaled by BC's own
Vesuvi 4 numbers. Damage is carried by ET_ENVIRONMENT_DAMAGE at 16 Hz: each
event that runs its destination's handler chain to the end lands 1/16 s of
drain (and one outage roll, Task 8); a handler that stops the chain cancels
it, as E3M2's CoreDamage and MissionLib.IgnoreEvent do in BC.

Design: docs/superpowers/specs/2026-09-23-radial-system-profile-design.md.
"""
from __future__ import annotations

import random

import App

from engine.core.ids import implements

EVENT_HZ = 16.0
HULL_PER_S = 150.0
SHIELD_PER_S = 20.0
DIFFICULTY_MULT = (0.0, 0.5, 1.0)


def _mult() -> float:
    from engine.core.game import Game_GetDifficulty
    level = Game_GetDifficulty()
    return DIFFICULTY_MULT[max(0, min(2, int(level)))]


def _fire(ship) -> bool:
    from engine.appc.events import dispatch_passes
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_ENVIRONMENT_DAMAGE)
    evt.SetDestination(ship)
    return dispatch_passes(evt)


class RadiationDriver:
    def __init__(self, sample_for, rng=None):
        self._sample_for = sample_for
        self._rng = rng if rng is not None else random.Random()
        self._accum = {}     # id(ship) -> seconds banked toward the next event

    def reset(self) -> None:
        self._accum.clear()

    def update(self, ships, dt, shared=frozenset()) -> None:
        """One fixed sim tick. `shared`: ids of ships inside an ARMED local
        MetaNebula -- their events come from NebulaTracker (Task 9)."""
        from engine.appc import warp_state
        m = _mult()
        period = 1.0 / EVENT_HZ
        live = set()
        for ship in ships:
            sid = id(ship)
            if m <= 0.0 or warp_state.is_ship_warping(ship) or sid in shared:
                continue
            r = self._sample_for(ship).radiation
            if r <= 0.0:
                continue
            live.add(sid)
            acc = self._accum.get(sid, 0.0) + dt
            while acc >= period:
                acc -= period
                if _fire(ship):
                    self.apply_chunk(ship, r, m)
            self._accum[sid] = acc
        for sid in list(self._accum):
            if sid not in live:
                del self._accum[sid]

    def apply_chunk(self, ship, radiation: float, mult: float) -> None:
        """1/16 s of drain: shields per face while up, else the hull."""
        from engine.appc.nebula_runtime import _shields_up
        dt = 1.0 / EVENT_HZ
        shields = _shields_up(ship)
        if shields is not None:
            per_face = SHIELD_PER_S * radiation * mult * dt
            for face in range(shields.NUM_SHIELDS):
                cur = shields.GetCurrentShields(face) - per_face
                shields.SetCurrentShields(face, cur if cur > 0.0 else 0.0)
        else:
            hull = ship.GetHull() if hasattr(ship, "GetHull") else None
            amount = HULL_PER_S * radiation * mult * dt
            if hull is not None and amount > 0.0:
                if implements(ship, "DamageSystem"):
                    ship.DamageSystem(hull, amount)
                else:
                    new = hull.GetCondition() - amount
                    hull.SetCondition(new if new > 0.0 else 0.0)
