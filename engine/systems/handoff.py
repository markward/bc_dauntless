"""The player hand-off between regions (in-system-warp design, section 3).

A star system's regions are the original BC sets, each anchored in the
system's own coordinate space (engine/systems/frames.py). Crossing from one
region's sphere into another's is an ORDINARY RemoveObjectFromSet /
AddObjectToSet -- the ordinary ET_EXITED_SET / ET_ENTERED_SET broadcast
already drives every mission's "Entering <set>" banner and region state
machine -- with the set-local position rebased by the anchor difference so
system_position() is identical before and after (rule A).

Only the player crosses this way (rule N): an NPC's own region travel is the
in-system-warp follow-up, out of scope here. `tick` gates on
App.Game_GetCurrentPlayer() for exactly that reason, not on its caller's
discipline alone -- host_loop calls it once per frame with session.player,
but a defensive gate costs nothing and matches every other player-only
effect in this tree (engine.appc.warp._is_current_player,
engine.appc.articulation._is_player).

Rule H (hysteresis). The player stays in its current set until beyond its
radius + HANDOFF_MARGIN_GU -- not the instant it crosses the bare radius --
so a position sitting exactly on a sphere's edge cannot flicker in and out
every tick.

Deferred during a dash (spec section 3): a player dash (a WarpFlight whose
speed_policy is "set_course" or "heading") never hands off mid-flight; the
drop-out itself (Task 4) calls `hand_off` directly once the flight has
ended, wherever it ended up. An "ai"-policy flight on the player -- an
autopilot Intercept -- is not a dash and does not defer.
"""
from __future__ import annotations

import math

from engine.systems import frames, region_hooks, resolve

HANDOFF_MARGIN_GU = 1500.0

# WarpFlight.speed_policy values that make the current flight a player dash
# (deferred to drop-out -- see .superpowers/sdd/2026-09-26-in-system-warp-
# plan/progress.md's ruling on this task).
_DASH_POLICIES = ("set_course", "heading")


def _is_current_player(ship) -> bool:
    """True when `ship` is the game's current player. Best-effort: False
    headlessly or whenever the game is not resolvable -- the same idiom as
    engine.appc.warp._is_current_player / engine.appc.articulation._is_player."""
    try:
        import App
        player = App.Game_GetCurrentPlayer()
    except Exception:
        return False
    return player is not None and player is ship


def _is_dashing(player) -> bool:
    flight = getattr(player, "_insystem_warp_transit", None)
    return (flight is not None
            and getattr(flight, "speed_policy", None) in _DASH_POLICIES)


def region_at(player):
    """The loaded, mapped region set of the player's system whose sphere
    (anchor_gu, radius_gu) contains its system position -- or None when it
    is in no such sphere (open space) or in no mapped system at all. When
    two loaded regions' spheres both contain it, the nearer anchor wins."""
    pSet = frames.containing_set(player)
    f = frames.frame_of(pSet)
    if f is None or f.key[0] != "system":
        return None
    m = resolve.map_of(f.key[1])
    pos = frames.system_position(player)
    if m is None or pos is None:
        return None
    _, x, y, z = pos
    import App
    best, best_d = None, None
    for name in resolve.regions_of(f.key[1]):
        candidate = App.g_kSetManager.GetSet(name)
        if candidate is None or not region_hooks.is_mapped(candidate):
            continue
        region = m.region(name)
        if region is None:
            continue
        d = math.dist((x, y, z), region.anchor_gu)
        if d <= region.radius_gu and (best is None or d < best_d):
            best, best_d = candidate, d
    return best


def tick(player):
    """Hand the player off into whichever region's sphere now contains it,
    and return the new set -- else None. No-op when: `player` is None or is
    not the current player (rule N); its set is unmapped; it is dashing
    (`_is_dashing`); it is still within its current set's radius +
    HANDOFF_MARGIN_GU (rule H); or no other region's sphere contains it."""
    if player is None or not _is_current_player(player):
        return None
    src = frames.containing_set(player)
    if src is None or not region_hooks.is_mapped(src):
        return None
    if _is_dashing(player):
        return None
    f = frames.frame_of(src)
    m = resolve.map_of(f.key[1])
    pos = frames.system_position(player)
    if m is None or pos is None:
        return None
    _, x, y, z = pos
    current = m.region(src.GetName())
    if current is not None:
        d_cur = math.dist((x, y, z), current.anchor_gu)
        if d_cur <= current.radius_gu + HANDOFF_MARGIN_GU:
            return None
    dest = region_at(player)
    if dest is None or dest is src:
        return None
    hand_off(player, dest)
    return dest


def hand_off(player, dest) -> None:
    """Move `player` from its current set into `dest`, keeping
    system_position() identical (rule A): set-local position rebased by the
    anchor difference, rotation and velocity untouched. The ordinary
    RemoveObjectFromSet / AddObjectToSet posts ET_EXITED_SET / ET_ENTERED_SET
    as it always has; `post_exited_warp` follows (rule A')."""
    src = frames.containing_set(player)
    name = player.GetName()
    off = frames.offset_between(dest, src)
    if off is None:
        off = (0.0, 0.0, 0.0)
    p = player.GetTranslate()
    local_dest = (p.x + off[0], p.y + off[1], p.z + off[2])
    if src is not None:
        src.RemoveObjectFromSet(name)
    dest.AddObjectToSet(player, name)
    player.SetTranslateXYZ(*local_dest)
    from engine.appc import warp
    warp._clear_all_targets(player)
    post_exited_warp(player)


def post_exited_warp(player) -> None:
    """Announce ET_EXITED_WARP for `player` (rule A'): after every impulse
    hand-off, and at every dash drop-out (Task 4 reuses this) -- including a
    drop-out that causes no hand-off at all."""
    import App
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_EXITED_WARP)
    evt.SetSource(player)
    evt.SetDestination(player)
    App.g_kEventManager.AddEvent(evt)
