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
from engine.appc.ships import ShipClass

# Ships the timed flythrough warp is currently flying (engine/appc/warp.py).
# A LIST, not a single slot: the SDK's Warp AI/action can warp an NPC out
# through the same entry point while the player's own flythrough is still
# mid-align (WarpSequence_Create takes the flythrough branch for any ship,
# with no player check), so more than one ship can be registered at once. A
# single global here would let the second registration silently overwrite
# the first, orphaning that ship at a non-WES_NOT_WARPING state forever (see
# C-1 in docs/superpowers/sdd/final-review-findings.md). Ordered list, not a
# set: TGObject defines no __hash__ contract to rely on. Only used to
# guarantee the flythrough's warp state cannot leak: the host loop syncs it
# to WES_NOT_WARPING once the warp animator goes inactive.
_flythrough_ships = []


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
    """Register a ship the timed flythrough warp is flying. Identity-checked
    (`is`) append: registering the same ship twice is a no-op, and registering
    a second, different ship does NOT evict the first — both stay tracked
    until each is individually released (see the module-level comment on
    _flythrough_ships)."""
    for existing in _flythrough_ships:
        if existing is ship:
            return
    _flythrough_ships.append(ship)


def flythrough_ship():
    """The most-recently-registered flythrough ship, or None. Kept for
    existing single-ship callers; prefer flythrough_ships() for anything that
    must see every registered ship."""
    return _flythrough_ships[-1] if _flythrough_ships else None


def flythrough_ships():
    """Every ship currently registered as flying a flythrough warp."""
    return list(_flythrough_ships)


def is_flythrough(ship) -> bool:
    """True iff `ship` is currently registered (identity, not just 'is a ship
    flying a flythrough at all' — use this, not `flythrough_ship() is ship`,
    when more than one ship may be registered)."""
    for existing in _flythrough_ships:
        if existing is ship:
            return True
    return False


def end_flythrough(ship=None) -> None:
    """Clear a flythrough ship's warp state and drop its registration.

    With a ship: release only that ship. With no argument: release EVERY
    registered ship (the warp animator is a singleton, so 'no warp active'
    means nobody is flying a flythrough — see sync_flythrough)."""
    if ship is None:
        ships = list(_flythrough_ships)
        _flythrough_ships.clear()
        for s in ships:
            set_state(s, WarpEngineSubsystem.WES_NOT_WARPING)
        return
    for i, existing in enumerate(_flythrough_ships):
        if existing is ship:
            del _flythrough_ships[i]
            break
    set_state(ship, WarpEngineSubsystem.WES_NOT_WARPING)


def sync_flythrough(warp_active: bool) -> None:
    """Leak guard: once the warp animator is no longer active, NO registered
    ship must still read as warping — otherwise an aborted warp would leave it
    non-collidable forever. The animator is a singleton, so this releases
    every registered ship, not just the most recent."""
    if not warp_active and _flythrough_ships:
        end_flythrough()


def reset() -> None:
    """Drop every flythrough registration without touching any ship (the
    ship(s) are being destroyed — mission swap)."""
    _flythrough_ships.clear()
