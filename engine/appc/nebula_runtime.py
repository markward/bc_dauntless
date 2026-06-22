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


def _ignores_env_damage(ship):
    """Check if ship has registered IgnoreEvent for ET_ENVIRONMENT_DAMAGE."""
    handlers = getattr(ship, "_handlers", None)
    if not handlers:
        return False
    return "MissionLib.IgnoreEvent" in handlers.get(App.ET_ENVIRONMENT_DAMAGE, [])


def _apply_env_damage(ship, hull_per_s, shield_per_s, dt):
    """Apply hull and shield damage if ship doesn't ignore ET_ENVIRONMENT_DAMAGE."""
    if hull_per_s <= 0.0 and shield_per_s <= 0.0:
        return
    # Only apply damage if ship has the necessary subsystems.
    if not hasattr(ship, "GetHull"):
        return
    if _ignores_env_damage(ship):
        return
    if hull_per_s > 0.0:
        hull = ship.GetHull()
        if hull is not None:
            new = hull.GetCondition() - hull_per_s * dt
            hull.SetCondition(new if new > 0.0 else 0.0)
    if shield_per_s > 0.0:
        shields = getattr(ship, "GetShieldSubsystem", None)
        if shields is not None:
            shields = shields()
            if shields is not None:
                per_face = (shield_per_s * dt) / shields.NUM_SHIELDS
                for face in range(shields.NUM_SHIELDS):
                    cur = shields.GetCurrentShields(face) - per_face
                    shields.SetCurrentShields(face, cur if cur > 0.0 else 0.0)


def _clamp01(v):
    """Clamp value to [0, 1]."""
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


class NebulaTracker:
    def __init__(self):
        # {id(nebula): set(id(ship))} — who is currently inside each nebula.
        self._inside = {}
        # {id(ship): base_range} — saved sensor ranges while scaled.
        self._sensor_saved = {}

    def reset(self):
        self._inside.clear()
        self._sensor_saved.clear()

    def _scale_sensor(self, ship, density):
        """Scale ship's sensor range by clamp(density, 0, 1). Save base on first scale."""
        sensor = ship.GetSensorSubsystem() if hasattr(ship, "GetSensorSubsystem") else None
        if sensor is None:
            return
        sid = id(ship)
        if sid in self._sensor_saved:
            return  # already scaled
        base = sensor.GetBaseSensorRange()
        self._sensor_saved[sid] = base
        sensor.SetBaseSensorRange(base * _clamp01(density))

    def _restore_sensor(self, ship):
        """Restore ship's sensor range to saved base.

        NOTE: single-nebula assumption — a ship simultaneously inside two
        distinct-density nebulae will have its sensor restored on the first
        exit. No target set (Vesuvi4/Multi5/Multi6) overlaps distinct nebulae,
        so this is deferred.
        """
        sid = id(ship)
        if sid not in self._sensor_saved:
            return
        sensor = ship.GetSensorSubsystem() if hasattr(ship, "GetSensorSubsystem") else None
        if sensor is not None:
            sensor.SetBaseSensorRange(self._sensor_saved[sid])
        del self._sensor_saved[sid]

    def update(self, pSet, ships, dt):
        nebulae = _nebulae_in_set(pSet)
        if not nebulae:
            # No nebula in this set: nothing to track. Drop any stale state
            # (e.g. after a set change) so re-entry fires a fresh ENTER.
            if self._inside:
                self._inside.clear()
            # Restore sensor ranges for any ships passed in (no-nebula path).
            for ship in ships:
                self._restore_sensor(ship)
            return

        for nebula in nebulae:
            key = id(nebula)
            prev = self._inside.get(key, set())
            now = set()
            hull_dmg, shield_dmg = nebula.GetDamage()
            density = nebula.GetSensorDensity()
            for ship in ships:
                if nebula.IsObjectInNebula(ship):
                    sid = id(ship)
                    now.add(sid)
                    if sid not in prev:
                        _fire(App.ET_ENTERED_NEBULA, nebula, ship)
                        self._scale_sensor(ship, density)
                    _apply_env_damage(ship, hull_dmg, shield_dmg, dt)
            # Exits: ships that were inside last tick but are not now.
            exited_ids = prev - now
            if exited_ids:
                by_id = {id(s): s for s in ships}
                for sid in exited_ids:
                    ship = by_id.get(sid)
                    if ship is not None:
                        _fire(App.ET_EXITED_NEBULA, nebula, ship)
                        self._restore_sensor(ship)
            self._inside[key] = now
