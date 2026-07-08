"""Engine-side defensive cloak-to-repair controller.

A crippled cloak-capable AI ship breaks off, cloaks, and repairs in hiding, then
re-engages once healed or is flushed out by reserve exhaustion (Part B). This is
an engine behavior overlaid on the SDK AI (same pattern as collision_avoidance):
while a ship is DEFENSIVE its SDK AI is suppressed (tick_all_ai skips it), so the
SDK CloakShip/focus lifecycle never fights this controller for the cloak.

Spec: docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md.
"""
from engine.appc.ship_iter import iter_ships
import engine.dev_mode as dev_mode

# Hull-condition thresholds (fraction 0..1). Hysteresis gap prevents thrash.
CLOAK_HULL_THRESHOLD: float = 0.35     # hide below this
FIT_TO_FIGHT_THRESHOLD: float = 0.70   # re-engage at/above this

# Per-ship mode: ships present in this set are DEFENSIVE (hiding). Absent == NORMAL.
_defensive: set = set()


def reset_defensive_cloak_state() -> None:
    """Clear all per-ship mode. Called on mission swap / test isolation (mirrors
    collision_avoidance.reset_avoidance_state)."""
    _defensive.clear()


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
    for ship in iter_ships():
        _update_ship(ship)


def _update_ship(ship) -> None:
    ai = ship.GetAI() if hasattr(ship, "GetAI") else None
    if ai is None:                       # never the player
        _defensive.discard(id(ship))
        return
    cloak = _functional_cloak(ship)
    if cloak is None:                    # cloak lost / no cloak -> leave DEFENSIVE
        if id(ship) in _defensive:
            _defensive.discard(id(ship))
        return
    hull_pct = _hull_pct(ship)
    if hull_pct is None:
        return

    if id(ship) in _defensive:
        # Exit conditions (healed-or-forced).
        if not cloak.IsTryingToCloak():             # forced out (reserve dry) or lost
            _defensive.discard(id(ship))
            _dev_log(ship, "re-engaging (forced out)")
            return
        if hull_pct >= FIT_TO_FIGHT_THRESHOLD:      # healed
            cloak.StopCloaking()
            _defensive.discard(id(ship))
            _dev_log(ship, "re-engaging (repaired %d%%)" % int(hull_pct * 100))
        return

    # Enter: crippled + in combat (has a target).
    target = ship.GetTarget() if hasattr(ship, "GetTarget") else None
    if hull_pct < CLOAK_HULL_THRESHOLD and target is not None:
        cloak.StartCloaking()
        _defensive.add(id(ship))
        _dev_log(ship, "defensive hide (hull %d%%)" % int(hull_pct * 100))
