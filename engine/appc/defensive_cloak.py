"""Engine-side defensive cloak-to-repair controller.

A crippled cloak-capable AI ship breaks off, cloaks, and repairs in hiding, then
re-engages once healed or is flushed out by reserve exhaustion (Part B). This is
an engine behavior overlaid on the SDK AI (same pattern as collision_avoidance):
while a ship is DEFENSIVE its SDK AI will be suppressed (tick_all_ai skips it,
Task 3), so the SDK CloakShip/focus lifecycle never fights this controller for
the cloak.

Spec: docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md.
"""
from engine.appc.ship_iter import iter_ships
import engine.dev_mode as dev_mode

# Hull-condition thresholds (fraction 0..1). Hysteresis gap prevents thrash.
CLOAK_HULL_THRESHOLD: float = 0.35     # hide below this
FIT_TO_FIGHT_THRESHOLD: float = 0.70   # re-engage at/above this

# Anti-thrash re-entry gate (fraction 0..1 of the backup reserve's limit). A
# ship forced out of DEFENSIVE by reserve exhaustion (Part B) has a ~0 reserve;
# without this gate it would immediately re-enter (still crippled, still
# targeted) and re-fire StartCloaking every few frames -- an audible/visual
# strobe that also defeats the "flushed out -> fight" behavior. Requiring the
# reserve to rebuild past this fraction before re-cloaking forces the ship to
# fight via its SDK AI while its reactor recovers: a weak reactor rebuilds
# slowly and stays out longer, a healthy one can hide again sooner.
CLOAK_REENTRY_RESERVE_FRACTION: float = 0.5

# Max seconds a ship may stay defensively cloaked in one episode. AI ships were
# hiding indefinitely; a hard cap forces them back out to fight. After a timeout
# the ship is held out of DEFENSIVE for DEFENSIVE_CLOAK_COOLDOWN_S so a healthy
# ship (reserve still full) can't just re-cloak on the next frame, which would
# make the timeout meaningless. Both tunable by eye.
DEFENSIVE_CLOAK_TIMEOUT_S: float = 60.0
DEFENSIVE_CLOAK_COOLDOWN_S: float = 60.0

# Per-ship mode: ships present in this set are DEFENSIVE (hiding). Absent == NORMAL.
_defensive: set = set()
# id(ship) -> seconds spent in the current DEFENSIVE episode (timeout accrual).
_elapsed: dict = {}
# id(ship) -> seconds remaining before a timed-out ship may re-enter DEFENSIVE.
_cooldown: dict = {}


def reset_defensive_cloak_state() -> None:
    """Clear all per-ship state. For test isolation / mission swap (mirrors
    collision_avoidance.reset_avoidance_state)."""
    _defensive.clear()
    _elapsed.clear()
    _cooldown.clear()


def _forget(sid: int, cooldown: float = 0.0) -> None:
    """Release a ship from DEFENSIVE: drop its mode + timeout accrual, and
    optionally start a re-hide cooldown."""
    _defensive.discard(sid)
    _elapsed.pop(sid, None)
    if cooldown > 0.0:
        _cooldown[sid] = cooldown


def is_defensive(ship) -> bool:
    """True while this ship is hiding-to-repair. tick_all_ai skips the SDK AI of
    such ships so the two cloak drivers never conflict."""
    return id(ship) in _defensive


def _functional_cloak(ship):
    """The ship's cloaking subsystem if present and usable, else None."""
    get = getattr(ship, "GetCloakingSubsystem", None)
    cloak = get() if callable(get) else None
    if cloak is None:
        return None
    if cloak.IsDisabled() or cloak.IsDestroyed():
        return None
    return cloak


def _hull_pct(ship):
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if hull is None:
        return None
    return hull.GetConditionPercentage()


def _dev_log(ship, verb: str) -> None:
    if not dev_mode.is_enabled():
        return
    name = ship.GetName() if hasattr(ship, "GetName") else "<ship>"
    print("[cloak] %s -> %s" % (name, verb))


def tick_defensive_cloak(dt: float) -> None:
    """Per-frame controller. Runs BEFORE tick_all_ai each frame; ships it marks
    DEFENSIVE have their SDK AI suppressed by tick_all_ai this frame."""
    ships = list(iter_ships())
    for ship in ships:
        _update_ship(ship, dt)

    # Drop state for ships that left play so the dicts can't grow unbounded
    # (mirrors collision_avoidance.tick_collision_avoidance).
    live = {id(s) for s in ships}
    _defensive.intersection_update(live)
    for d in (_elapsed, _cooldown):
        for sid in [k for k in d if k not in live]:
            del d[sid]


def _update_ship(ship, dt) -> None:
    sid = id(ship)
    ai = ship.GetAI() if hasattr(ship, "GetAI") else None
    if ai is None:                       # never the player
        _forget(sid)
        return
    cloak = _functional_cloak(ship)
    if cloak is None:                    # cloak lost / no cloak -> leave DEFENSIVE
        _forget(sid)
        return
    hull_pct = _hull_pct(ship)
    if hull_pct is None:
        return

    if sid in _defensive:
        elapsed = _elapsed.get(sid, 0.0) + float(dt)
        _elapsed[sid] = elapsed
        # Exit conditions (forced-out / healed / timed-out).
        if not cloak.IsTryingToCloak():             # forced out (reserve dry) or lost
            _forget(sid)
            _dev_log(ship, "re-engaging (forced out)")
            return
        if hull_pct >= FIT_TO_FIGHT_THRESHOLD:      # healed
            cloak.StopCloaking()
            _forget(sid)
            _dev_log(ship, "re-engaging (repaired %d%%)" % int(hull_pct * 100))
            return
        if elapsed >= DEFENSIVE_CLOAK_TIMEOUT_S:     # hidden too long -> come out and fight
            cloak.StopCloaking()
            _forget(sid, cooldown=DEFENSIVE_CLOAK_COOLDOWN_S)
            _dev_log(ship, "re-engaging (timeout)")
        return

    # NORMAL: run down any post-timeout re-hide cooldown.
    if sid in _cooldown:
        _cooldown[sid] -= float(dt)
        if _cooldown[sid] <= 0.0:
            _cooldown.pop(sid, None)

    # Enter: crippled + in combat (has a target), reserve recovered, not cooling down.
    target = ship.GetTarget() if hasattr(ship, "GetTarget") else None
    if hull_pct < CLOAK_HULL_THRESHOLD and target is not None:
        if sid in _cooldown:                         # still fighting off a recent timeout
            return
        if not _reserve_recovered(ship):
            return
        cloak.StartCloaking()
        _defensive.add(sid)
        _elapsed[sid] = 0.0
        _dev_log(ship, "defensive hide (hull %d%%)" % int(hull_pct * 100))


def _reserve_recovered(ship) -> bool:
    """Anti-thrash gate for entering DEFENSIVE (see CLOAK_REENTRY_RESERVE_FRACTION).
    No PowerSubsystem / no usable backup limit -> ungated (existing behavior)."""
    get_power = getattr(ship, "GetPowerSubsystem", None)
    power = get_power() if callable(get_power) else None
    if power is None:
        return True
    limit = power.GetBackupBatteryLimit() if hasattr(power, "GetBackupBatteryLimit") else None
    if not limit:                        # None or 0/unavailable -> ungated
        return True
    reserve = power.GetBackupBatteryPower() if hasattr(power, "GetBackupBatteryPower") else 0.0
    return reserve >= CLOAK_REENTRY_RESERVE_FRACTION * limit
