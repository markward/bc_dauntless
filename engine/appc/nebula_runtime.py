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


# ── Environmental damage, as the original exe applies it ─────────────────────
# Measured on stbc.exe (stbc-oracle bible §15, E1, `docs/results/nebula/*`):
# a SetupDamage(hull, shields) nebula raises ET_ENVIRONMENT_DAMAGE on every
# contained ship 16 times a second for as long as it is inside — but the only
# DAMAGE is ONE hit, to a ship that is already inside when the nebula is
# created: `shields / 16` to every face if the shields are up (discarded when
# ≤ 100 per face), else `hull / 16` to the hull (no threshold). A ship that
# flies into an existing nebula takes nothing while the events keep coming.
# Nothing lands at easy difficulty. The 1/16 is the event rate: the stock
# nebula was authored as damage-per-second and the engine applies one tick's
# worth, once. So the E3M2 dust cloud never damages the player, who warps in
# after Vesuvi 4 is built; Brex's "raise shields" line is the SDK's
# CoreDamage reacting to the events.
#
# This replaced a continuous `per-second × dt` drain to everyone inside,
# which had the player in E3M2 losing 150 hull a second.
ENV_DAMAGE_EVENT_HZ = 16.0
ENV_DAMAGE_FRACTION = 1.0 / 16.0
ENV_SHIELD_HIT_THRESHOLD = 100.0


def _shields_up(ship):
    """The face-hit branch applies when the shields are raised."""
    getter = getattr(ship, "GetShieldSubsystem", None)
    shields = getter() if getter is not None else None
    if shields is None:
        return None
    is_on = getattr(shields, "IsOn", None)
    if callable(is_on):
        return shields if is_on() else None
    total = 0.0
    for face in range(shields.NUM_SHIELDS):
        total += shields.GetCurrentShields(face)
    return shields if total > 0.0 else None


def _apply_creation_hit(ship, hull_arg, shield_arg):
    """The one hit a ship present at the nebula's creation takes."""
    if hull_arg <= 0.0 and shield_arg <= 0.0:
        return
    if not hasattr(ship, "GetHull"):
        return
    if _ignores_env_damage(ship):
        return
    from engine.core.game import Game_GetDifficulty
    if Game_GetDifficulty() <= 0:
        return                                   # easy: nothing lands
    shields = _shields_up(ship)
    if shields is not None:
        per_face = shield_arg * ENV_DAMAGE_FRACTION
        if per_face <= ENV_SHIELD_HIT_THRESHOLD:
            return                               # discarded, hull untouched
        for face in range(shields.NUM_SHIELDS):
            cur = shields.GetCurrentShields(face) - per_face
            shields.SetCurrentShields(face, cur if cur > 0.0 else 0.0)
        return
    hull = ship.GetHull()
    if hull is not None and hull_arg > 0.0:
        new = hull.GetCondition() - hull_arg * ENV_DAMAGE_FRACTION
        hull.SetCondition(new if new > 0.0 else 0.0)


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
        # {id(nebula): seconds banked toward the next ET_ENVIRONMENT_DAMAGE}.
        self._env_accum = {}

    def reset(self):
        self._inside.clear()
        self._sensor_saved.clear()
        self._env_accum.clear()

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
            if self._sensor_saved:
                for ship in ships:
                    self._restore_sensor(ship)
            return

        for nebula in nebulae:
            key = id(nebula)
            first_sighting = key not in self._inside
            prev = self._inside.get(key, set())
            now = set()
            hull_dmg, shield_dmg = nebula.GetDamage()
            density = nebula.GetSensorDensity()
            # ET_ENVIRONMENT_DAMAGE at 16 Hz to every occupant, damage or not.
            armed = hull_dmg > 0.0 or shield_dmg > 0.0
            accum = self._env_accum.get(key, 0.0) + dt
            fire_env = armed and accum >= 1.0 / ENV_DAMAGE_EVENT_HZ
            if fire_env:
                accum -= 1.0 / ENV_DAMAGE_EVENT_HZ
            self._env_accum[key] = accum
            for ship in ships:
                if nebula.IsObjectInNebula(ship):
                    sid = id(ship)
                    now.add(sid)
                    if sid not in prev:
                        _fire(App.ET_ENTERED_NEBULA, nebula, ship)
                        self._scale_sensor(ship, density)
                        if first_sighting:
                            # Present when the nebula was created: the one hit.
                            _apply_creation_hit(ship, hull_dmg, shield_dmg)
                    if fire_env:
                        _fire(App.ET_ENVIRONMENT_DAMAGE, nebula, ship)
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
