"""Per-sim-tick nebula membership tracking.

Diffs which ships are inside which MetaNebula each tick and broadcasts
ET_ENTERED_NEBULA / ET_EXITED_NEBULA. Environmental damage and sensor
scaling are layered on in nebula_runtime (Task 3). No GL — pure gameplay.

Mirrors the SDK's Conditions/ConditionInNebula.py event contract: the
source of each event is the nebula, the destination is the ship.
"""
import App


def _nebulae_in_set(pSet):
    """MetaNebula objects in pSet (empty list when none — cheap early-out)."""
    out = []
    for obj in pSet.GetClassObjectList(App.CT_NEBULA):
        neb = App.MetaNebula_Cast(obj)
        if neb is not None:
            out.append(neb)
    return out


def _fire(event_type, nebula, ship):
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetSource(nebula)
    evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)


class NebulaTracker:
    def __init__(self):
        # {id(nebula): set(id(ship))} — who is currently inside each nebula.
        self._inside = {}

    def reset(self):
        self._inside.clear()

    def update(self, pSet, ships, dt):
        nebulae = _nebulae_in_set(pSet)
        if not nebulae:
            # No nebula in this set: nothing to track. Drop any stale state
            # (e.g. after a set change) so re-entry fires a fresh ENTER.
            if self._inside:
                self._inside.clear()
            return

        for nebula in nebulae:
            key = id(nebula)
            prev = self._inside.get(key, set())
            now = set()
            for ship in ships:
                if nebula.IsObjectInNebula(ship):
                    sid = id(ship)
                    now.add(sid)
                    if sid not in prev:
                        _fire(App.ET_ENTERED_NEBULA, nebula, ship)
            # Exits: ships that were inside last tick but are not now.
            exited_ids = prev - now
            if exited_ids:
                by_id = {id(s): s for s in ships}
                for sid in exited_ids:
                    ship = by_id.get(sid)
                    if ship is not None:
                        _fire(App.ET_EXITED_NEBULA, nebula, ship)
            self._inside[key] = now
