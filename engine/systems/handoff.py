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

Containment (Mark, 2026-09-28: arriving near a planet from ANY direction
counts as entering its region). A region contains the player inside its
sphere OR within region_reach(body) = arrival_range(body) + HANDOFF_MARGIN_GU
of any body it owns. The sphere alone sits on its Player Start side of the
planet, so an approach from the far side used to stop beside the planet but
outside its region. Where two regions both contain a point, the one whose
nearest shape centre (anchor or owned body) is closest wins.

Rule H (hysteresis). The player stays in its current set until beyond its
radius + HANDOFF_MARGIN_GU of the sphere AND beyond reach + HANDOFF_MARGIN_GU
of every body it owns -- not the instant it crosses either bare edge -- so a
position sitting exactly on a sphere's or a reach's edge cannot flicker in
and out every tick.

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


_ARRIVAL_PLACEMENT = "Player Start"


def arrival_range(body) -> float | None:
    """From ``body``'s centre, the distance to its owning region's arrival
    point -- the region set's "Player Start", in system coordinates -- where
    the tunnel frames it. None when the body has no owning region or that
    region's set (or its Player Start) is not loaded. The ONE definition:
    the heading dash's body drop-out (engine.appc.dash._heading_standoffs)
    and the hand-off's reach (``region_reach``) both read it, so the point a
    dash stops at and the point that counts as arrived cannot drift apart."""
    if not getattr(body, "owner_region", None):
        return None
    import App
    pSet = App.g_kSetManager.GetSet(body.owner_region)
    wp = pSet.GetObject(_ARRIVAL_PLACEMENT) if pSet is not None else None
    arrival = frames.system_position(wp) if wp is not None else None
    if arrival is None:
        return None
    return math.dist(tuple(float(c) for c in body.position_gu),
                     tuple(arrival[1:]))


def region_reach(body) -> float:
    """How near ``body``'s centre counts as inside its owning region (Mark,
    2026-09-28: arriving near a planet from ANY side enters its region):
    arrival_range + HANDOFF_MARGIN_GU, else 2 * radius + HANDOFF_MARGIN_GU
    when the arrival range is unknown."""
    ar = arrival_range(body)
    base = ar if ar is not None else 2.0 * body.radius_gu
    return base + HANDOFF_MARGIN_GU


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


def _shape_distance(m, region, pos, margin=0.0) -> float | None:
    """How near ``pos`` is to ``region``, or None when the region does not
    contain it. It contains it inside its sphere (anchor_gu, radius_gu) OR
    within ``region_reach`` of the centre of any body it owns (map
    Body.owner_region) -- each shape widened by ``margin``. The distance is
    to the nearest of those shape centres (the anchor, every owned body),
    the tie-break when two regions both contain the point."""
    shapes = [(tuple(region.anchor_gu), region.radius_gu)]
    for b in m.bodies:
        if b.owner_region == region.set_name:
            shapes.append((tuple(float(c) for c in b.position_gu),
                           region_reach(b)))
    inside, nearest = False, None
    for centre, reach in shapes:
        d = math.dist(pos, centre)
        inside = inside or d <= reach + margin
        nearest = d if nearest is None else min(nearest, d)
    return nearest if inside else None


def nearest_region(m, pos, names):
    """Of the region set ``names`` in map ``m``, the name of the one that
    contains system point ``pos`` (``_shape_distance``) -- or None. When
    several do, the one whose nearest shape centre (sphere anchor or owned
    body) is closest wins; an exact tie goes to the lower set name, so the
    choice never depends on map order."""
    best = None
    for name in names:
        region = m.region(name)
        if region is None:
            continue
        d = _shape_distance(m, region, pos)
        if d is not None and (best is None or (d, name) < best):
            best = (d, name)
    return best[1] if best is not None else None


def region_at(player):
    """The loaded, mapped region set of the player's system that contains
    its system position (``nearest_region``: inside the region's sphere, or
    within reach of a body it owns) -- or None when it is in no region (open
    space) or in no mapped system at all."""
    pSet = frames.containing_set(player)
    f = frames.frame_of(pSet)
    if f is None or f.key[0] != "system":
        return None
    m = resolve.map_of(f.key[1])
    pos = frames.system_position(player)
    if m is None or pos is None:
        return None
    import App
    loaded = {}
    for name in resolve.regions_of(f.key[1]):
        candidate = App.g_kSetManager.GetSet(name)
        if candidate is not None and region_hooks.is_mapped(candidate):
            loaded[name] = candidate
    name = nearest_region(m, tuple(pos[1:]), list(loaded))
    return loaded.get(name) if name is not None else None


def tick(player):
    """Hand the player off into whichever region now contains it, and
    return the new set -- else None. No-op when: `player` is None or is
    not the current player (rule N); its set is unmapped; it is dashing
    (`_is_dashing`); its current region still contains it with every shape
    widened by HANDOFF_MARGIN_GU -- within radius + margin of its sphere or
    reach + margin of a body it owns (rule H); or no other region contains
    it."""
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
    current = m.region(src.GetName())
    if current is not None and _shape_distance(
            m, current, tuple(pos[1:]), HANDOFF_MARGIN_GU) is not None:
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
        # src and dest are in different frames -- not a hand-off this module
        # can rebase honestly (rule A requires both regions of one system).
        # Every real caller (tick's own rule-H gate; Task 4's dash drop-out,
        # which never leaves the flight's originating region until it ends)
        # only ever calls this with two sets of the SAME mapped system, so
        # reaching here is a caller bug -- fail loud rather than silently
        # mis-placing the player at its old raw coordinates in a new system.
        raise ValueError(
            "handoff.hand_off: %r and %r are not in the same frame" % (
                getattr(dest, "GetName", lambda: dest)(),
                getattr(src, "GetName", lambda: src)()))
    p = player.GetTranslate()
    local_dest = (p.x + off[0], p.y + off[1], p.z + off[2])
    if src is not None:
        src.RemoveObjectFromSet(name)
    dest.AddObjectToSet(player, name)
    player.SetTranslateXYZ(*local_dest)
    # Clear the target alone -- no _stand_down_player_ai, unlike the tunnel's
    # engage-time clear (engine/appc/warp.py:_ClearTargetsAction). Mirrors the
    # tunnel's ARRIVAL clear instead (_ArrivalClearTargetsAction): the old
    # set's ships have just left the target list's pool (it is derived from
    # the player's containing set), so the same "don't retarget across a set
    # boundary" reasoning applies, but standing the player's AI down on every
    # impulse crossing would cancel a still-valid order (an Intercept/Orbit
    # that crosses a region boundary mid-flight must keep running).
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
