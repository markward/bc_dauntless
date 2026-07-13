"""Ship-level warp-state facade over WarpEngineSubsystem's WES_* machine.

BC's canonical "is this ship warping?" test is
`GetWarpEngineSubsystem().GetWarpState() != WES_NOT_WARPING` — the same test
its own scripts make (WarpSequence.py:638, HelmMenuHandlers.py:2465,
ConditionInRange.py:209). Every engine read/write of that state goes through
this module so the stub guards live in one place.

THE GUARD THAT MATTERS: is_ship_warping() is isinstance(ShipClass)-checked.
A Planet has no GetWarpEngineSubsystem, so TGObject.__getattr__ returns a
truthy _Stub, calling it returns a _Stub, and `_Stub != WES_NOT_WARPING` is
True (App.py:1955) — duck-typing here would mark every planet, moon and sun in
the game as warping, and (via collisions._collisions_enabled) make them all
non-collidable.

Spec: docs/superpowers/specs/2026-07-13-warp-collision-suppression-design.md
"""

from engine.appc.subsystems import WarpEngineSubsystem

# The ship the timed flythrough warp is currently flying (engine/appc/warp.py),
# or None. Only used to guarantee the flythrough's warp state cannot leak: the
# host loop syncs it to WES_NOT_WARPING once the warp animator goes inactive.
_flythrough_ship = None


def _warp_subsystem(ship):
    """The ship's WarpEngineSubsystem, or None. Ships can legitimately be built
    without one, and GetWarpEngineSubsystem() then returns a real None."""
    sub = ship.GetWarpEngineSubsystem()
    return sub if isinstance(sub, WarpEngineSubsystem) else None


def get_state(ship) -> int:
    """The ship's warp state; WES_NOT_WARPING when it has no warp subsystem."""
    sub = _warp_subsystem(ship)
    if sub is None:
        return WarpEngineSubsystem.WES_NOT_WARPING
    return sub.GetWarpState()


def set_state(ship, state) -> None:
    """Set the ship's warp state. No-op when it has no warp subsystem."""
    sub = _warp_subsystem(ship)
    if sub is not None:
        sub.SetWarpState(state)


def is_ship_warping(obj) -> bool:
    """True only for a ShipClass whose warp state is not WES_NOT_WARPING.

    isinstance-guarded on purpose — see the module docstring. Never rewrite
    this as a hasattr/getattr probe."""
    from engine.appc.ships import ShipClass
    if not isinstance(obj, ShipClass):
        return False
    sub = _warp_subsystem(obj)
    return False if sub is None else sub.IsWarping()


def tick_warp_states(dt: float) -> None:
    """Advance every ship's pending dewarp transition (see
    WarpEngineSubsystem.TransitionToState). Call once per frame BEFORE
    collisions.tick_collisions, so a dewarp that completes this frame is
    collidable this frame rather than next."""
    from engine.appc.ship_iter import iter_ships
    for ship in iter_ships():
        sub = _warp_subsystem(ship)
        if sub is not None:
            sub.tick_transition(dt)


def begin_flythrough(ship) -> None:
    """Register the ship the timed flythrough warp is flying."""
    global _flythrough_ship
    _flythrough_ship = ship


def flythrough_ship():
    return _flythrough_ship


def end_flythrough() -> None:
    """Clear the flythrough ship's warp state and drop the registration."""
    global _flythrough_ship
    ship = _flythrough_ship
    _flythrough_ship = None
    if ship is not None:
        set_state(ship, WarpEngineSubsystem.WES_NOT_WARPING)


def sync_flythrough(warp_active: bool) -> None:
    """Leak guard: once the warp animator is no longer active, the flythrough
    ship must not still read as warping — otherwise an aborted warp would leave
    it non-collidable forever."""
    if not warp_active and _flythrough_ship is not None:
        end_flythrough()


def reset() -> None:
    """Drop the flythrough registration without touching any ship (the ship is
    being destroyed — mission swap)."""
    global _flythrough_ship
    _flythrough_ship = None
