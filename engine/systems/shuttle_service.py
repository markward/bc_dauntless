"""The Tau Ceti shuttle service: ten Federation shuttles between Starbase 12
and the Dry Docks.

A shuttle is a record, not a world object, while it is docked: it is in no set
and costs nothing. `_launch` puts it into the Starbase 12 set at the bay's
"Docking Exit Start"; `_dock` takes it out again. The service runs in every
game mode, belongs to no mission group, and pauses (every shuttle docked,
timers frozen) while the player is in another system or an excluded mission
is current (_EXCLUDED_MISSIONS, controller ruling R9: E8M2). Away rule: only
a player in a system other than Tau Ceti pauses it; no live player, or the
player in the warp transit set, leaves it exactly as it is. Docking a shuttle
stops any NPC warp it is flying (a flythrough would otherwise drop it into
its destination later), and reset() takes every ship it still has out of the
world.

Each flying phase is one leg: `_enter` sets the phase and hands the ship the
leg's AI (`_give_ai`); a leg ends when that AI reports done (the AI driver
clears a finished tree) or the leg's own completion test holds. The Starbase
12 legs:

- UNDOCKING: BC's AI.Compound.UndockFromStarbase, then out along the bay axis
  to a clearance point beyond "Docking Exit End". Pushed out of the bay by
  BC's player docking, or the bay taken by the player: DEPARTING at once,
  collisions with the station off until clear of it.
- DEPARTING: intercept to the shuttle's own lane point.
- WARPING_OUT: BC's Warp to its own Dry Docks lane point; done once in
  DryDock and out of warp.
- APPROACHING: intercept to its own point round a clearance point outside
  the bay mouth; it holds there while the bay is taken.
- ENTERING: FollowWaypoints to that clearance point on the bay axis, then
  "Docking Entry" -> "Docking Entry End" (built the way
  DockWithStarbase.MakeWaypoints builds them), then docked.
- WAITING: Starbase 12 missing or dead; hold at its lane point until it is
  back.

One shuttle in the bay at a time: none launches or enters while another is
UNDOCKING or ENTERING, or while the player docks, is docked or undocks.
Arrivals first: a due shuttle stays docked while another holds outside the
bay. While the bay is the player's, the service's shuttles are kept out of
BC's docking restore record (DockWithStarbase.g_kRestoreTranslateDict), which
would otherwise teleport them back into the bay when the player undocks.
Every shuttle has its own point (a 50 GU ring, ten points 31 GU apart) round
each region's lane point, where it arrives, departs and holds, and its own
holding point round the bay's clearance point, so two shuttles never share a
spot even once the one-a-minute stagger has drifted.

Collisions with Starbase 12 are off on the bay legs (UNDOCKING, ENTERING) and
back on after. AI.Compound.DockWithStarbase itself is never used: it takes
the player's camera and starts a cutscene.

The Dry Docks legs:

- TO_DOCK: intercept to a random standing dry dock ("Dry Dock", "Dry Dock2",
  "Dry Dock3"; the service's own Random) with a free orbit, among those the
  fewest other shuttles are bound for, stopping at the orbit's outer edge.
  No dock with a free orbit: hold at its own Dry Docks lane point.
- CIRCLING: BC's CircleObject round it, left side in, on its own orbit band,
  until the dock -> shuttle direction has turned CIRCLES full turns (real
  motion only) and it is the outermost shuttle there; else whole turns more.
- LEAVING_DOCKS: intercept to its own Dry Docks lane point.
- WARPING_BACK: BC's Warp to its own Starbase 12 lane point; done once in
  Starbase12 and out of warp, then APPROACHING.

Orbit bands come from the dock layout (controller ruling R7), not from the
plan's 40 / 60 GU floors, which it supersedes: Dry Dock and Dry Dock3 are 89
GU apart, so orbits that wide would cross. See _ORBIT_FLOOR_GU. Orbits fill
outwards and empty inwards, one shuttle flying in or out per dock at a time,
so no shuttle crosses another's orbit.

The chosen dock destroyed or gone on TO_DOCK or CIRCLING: choose again;
none standing: LEAVING_DOCKS.

Obstacle avoidance (controller ruling R10): the open-space legs and holds
(DEPARTING, TO_DOCK, LEAVING_DOCKS, APPROACHING, WAITING, the lane and
approach holds) run inside BC's AvoidObstacles preprocessor (`_avoiding`),
as the SDK's own compound AIs do; the engine has no other avoidance. The bay
legs (UNDOCKING, ENTERING) and CIRCLING are not wrapped, so avoidance never
pushes a shuttle off its circle or out of the bay. Where a wrapped leg flies
at its own target station, that station is out of the scan through the
per-pair collision mask the preprocessor reads: the dry dock on TO_DOCK (kept
through CIRCLING, lifted for LEAVING_DOCKS). Avoidance runs nowhere during an
in-system warp (BC skips it there). The docks and the Station are otherwise
cleared by route geometry, measured against today's layout
(home_stations.json): a change to where the Dry Docks stations stand must be
re-measured.

Losses: a shuttle whose ship dies (ship_lifecycle "destroyed") is LOST until
reset() (a mission change) and recorded as a `Loss` (`losses()`), with the
name of whoever fired the blow that started its death. A Quick Battle is a
simulation (`install(qb)`): a loss during it is never recorded, and when it
ends every shuttle it damaged or destroyed is DOCKED again, wherever it was,
with a fresh ship at its next launch. A set rebuilt (`on_region_built`) or
deleted outright docks only the shuttles that were in it.
"""
from __future__ import annotations

import enum
import logging
import math
import random
from dataclasses import dataclass

from engine.appc import ship_lifecycle
from engine.systems import owners

_log = logging.getLogger(__name__)

COUNT = 10
DOCK_S = 600.0
CIRCLES = 2
LANE_GU = 2000.0
LANE_NAME = "SB12 Shuttle Lane"
OWNER_NAME = "tau_ceti_shuttles"
SCRIPT = "Shuttle"
SYSTEM_ID = "tauceti"
HOME_SET = "Starbase12"
FAR_SET = "DryDock"
# set name -> the home station its lane point is measured from
_ANCHORS = {HOME_SET: "Starbase 12", FAR_SET: "Dry Dock"}
_BAY_EXIT = "Docking Exit Start"
_STAGGER_S = 60.0
# Intercepts to a shuttle's own point (lane, hold, approach) end this close:
# that point is where it arrives, departs and holds.
_POINT_GU = 10.0
_IN_SYSTEM_WARP_GU = 150.0
# Each shuttle's own point is on a ring of this radius round the region's
# lane point (and round the bay's outside clearance point): ten points 31 GU
# apart, so two shuttles never share an arrival, departure or holding spot.
_RING_GU = 50.0
# Clearance points, this far out along the bay axis from the bay mouth. The
# bay is a radial slot 68-108 GU from Starbase 12's centre; a shuttle leaves
# and arrives on the bay axis, and Starbase 12's lane lies on it too
# (_lane_axis).
_CLEAR_GU = 150.0
_EXIT_POINT = "SB12 Shuttle Exit"
_APPROACH_POINT = "SB12 Shuttle Approach"
_ENTRY = "Docking Entry"
_ENTRY_END = "Docking Entry End"
# An ENTERING shuttle farther than this from "Docking Entry" was moved off the
# bay path (BC's player docking clears 300 GU round it): it approaches again.
# The approach ends within _POINT_GU of a ring point ~158 GU from it.
_PUSHED_GU = 275.0
# A shuttle leaving the bay early (pushed, or the player took the bay) keeps
# collisions with Starbase 12 off until this far from its centre: clear of
# its ~150 GU hull bound.
_STATION_CLEAR_GU = 200.0
# A departing shuttle with Starbase 12 between it and its lane (pushed out
# of the bay through to the far side) first flies at impulse to this point,
# abreast of the station on the shuttle's side, square to the bay axis, this
# far beyond the station's radius (no less than _STATION_CLEAR_GU, so the
# station's collisions are back on by the time it gets there). From there
# the line to its lane misses the station, so BC's Intercept never detours
# round it (_lane_axis).
_ROUND_POINT = "SB12 Shuttle Round"
_ROUND_MARGIN_GU = 50.0
# FollowWaypoints is done within 8 GU of its last waypoint.
_DOCKED_GU = 20.0
# The player this close to the bay mouth ("Docking Entry Start") owns the bay
# even with no docking AI: just undocked and coasting out along the bay axis
# (BC's FinishedUndocking hands the player FlyForward), or parked there.
# Below BC's 300 GU docking clear on purpose: Starbase12's "Player Start" is
# ~225 GU from the mouth, and a free-roam start must not stop the service.
_BAY_NEAR_GU = 200.0
# The AI.Compound modules whose tree on the player means the bay is in use.
_BAY_AI_MODULES = ("DockWithStarbase", "UndockFromStarbase")
# The dry docks a shuttle circles (home stations in DryDock).
_DRY_DOCKS = ("Dry Dock", "Dry Dock2", "Dry Dock3")
# Orbit bands round a dry dock, from the layout (controller ruling R7; the
# plan's 40 / 60 GU floors are superseded -- Dry Dock and Dry Dock3 are 89 GU
# apart, so orbits that wide would cross). No orbit inside max(2 x the dock's
# hull radius, _ORBIT_FLOOR_GU); none beyond half the distance to the nearest
# other standing station in DryDock minus _ORBIT_CAP_MARGIN_GU, so orbits
# round two docks never meet. Bands are _BAND_GU wide, _BAND_GAP_GU apart,
# the first _BAND_INSET_GU outside the floor: CircleObject dips up to ~1.7
# GU inside a band's near edge while it spirals in from the far edge (then
# holds near + 1.0), and an intercept stopping at the far edge stops ~0.5 GU
# inside it (measured).
_ORBIT_FLOOR_GU = 20.0
_ORBIT_CAP_MARGIN_GU = 5.0
_BAND_GU = 7.0
_BAND_GAP_GU = 3.0
_BAND_INSET_GU = 2.0
# A shuttle that left a dock is still on its way out (in the corridor towards
# the lane) this close to it.
_DOCK_CLEAR_GU = 200.0
# Missions the service stays out of (controller ruling R9): while one is
# current every shuttle stays docked, as when the player is away. A mission
# is listed when its own set handlers act on ships they do not filter by
# name or group in Starbase12 or DryDock. E8M2: EnterSet (E8M2.py:1533-1537)
# targets, for the player, every ship but the Chairo entering Starbase12
# before Omega Draconis 5. Audit of the other missions using the two sets:
# docs/engine/home-stations.md, "Mission exclusions".
_EXCLUDED_MISSIONS = frozenset({"Maelstrom.Episode8.E8M2.E8M2"})
# Distinct tick-failure lines printed at most (type + first 120 characters).
_TICK_ERRORS_MAX = 16


class Phase(enum.Enum):
    DOCKED = 1
    UNDOCKING = 2
    DEPARTING = 3
    WARPING_OUT = 4
    TO_DOCK = 5
    CIRCLING = 6
    LEAVING_DOCKS = 7
    WARPING_BACK = 8
    APPROACHING = 9
    ENTERING = 10
    WAITING = 11
    LOST = 12


@dataclass
class Shuttle:
    index: int
    name: str
    phase: Phase = Phase.DOCKED
    ship: object = None
    timer: float = 0.0
    dock_name: str | None = None
    bearing_accum: float = 0.0
    bearing_prev: tuple | None = None   # dock -> shuttle last tick (dock frame)
    orbit_slot: int = 0          # which of the dock's orbits it circles on
    leave_at: float = 0.0        # bearing_accum at which it may next leave
    ai: object = None            # the AI the current leg gave the ship
    leg: Phase | None = None     # the phase `ai` was given for
    bay_station: object = None   # collisions with it are off (a bay leg)
    dock_mask: object = None     # the dry dock it is bound for or circles:
                                 # collisions (and so avoidance) with it off
    held: bool = False           # holding: outside the bay, or for a dock
    killer: str | None = None    # who fired the blow that started its death


@dataclass
class Loss:
    """One shuttle destroyed outside a Quick Battle: which, in which set, at
    what game time, and who fired the blow that started its death (None when
    unattributed)."""
    index: int
    name: str
    set_name: str
    game_time: float
    killer: str | None


class _Battle:
    """The running Quick Battle, as far as the shuttles go."""

    def __init__(self):
        # index -> subsystem conditions when the battle started, or when the
        # shuttle launched during it.
        self.start: dict = {}
        # index -> the dead ship of a shuttle lost during the battle.
        self.lost: dict = {}


_roster: list = []
_losses: list = []
_battle = None   # a _Battle while a Quick Battle runs
_started = False
_away = False
_bay_busy = False
_rng = random.Random()
_tick_errors: set = set()
_enabled = True   # the dev-only off switch (dev_render_off "shuttle_service")


def roster() -> list:
    return _roster


def losses() -> list:
    """Every shuttle lost since the last reset() (mission change), oldest
    first. A loss during a Quick Battle is never recorded."""
    return list(_losses)


def enabled() -> bool:
    return _enabled


def set_enabled(flag: bool) -> None:
    """The dev-only off switch, for a with/without cost capture
    (DAUNTLESS_DEV_RENDER_OFF=shuttle_service, engine/dev_render_off.py).
    Off: every flying shuttle docks and tick does nothing. Kept across
    reset() (a mission change); never persisted."""
    global _enabled
    _enabled = bool(flag)
    if _enabled:
        return
    for s in _roster:
        if s.phase not in (Phase.DOCKED, Phase.LOST):
            try:
                _dock(s)
            except Exception as exc:  # noqa: BLE001 - dock the rest anyway
                _park(s, exc)


def set_rng(rng: random.Random) -> None:
    global _rng
    _rng = rng


def reset() -> None:
    """Forget the roster and everything running. The owner stays registered.
    A ship still in the world (a mission change keeps BC's "warp" set, so a
    shuttle mid warp would be orphaned there) has its warp stopped, its AI
    dropped and is taken out of every set."""
    global _started, _away, _bay_busy, _battle
    for s in _roster:
        if s.ship is None:
            continue
        try:
            _stop_warp(s.ship)
            s.ship.ClearAI()
            _remove_from_sets(s.ship)
        except Exception:  # noqa: BLE001 - reset must forget the rest anyway
            _log.exception("shuttles: taking %s out on reset failed", s.name)
    _roster.clear()
    _losses.clear()
    _battle = None
    _started = False
    _away = False
    _bay_busy = False
    _tick_errors.clear()


# ── Lanes ────────────────────────────────────────────────────────────────────

def _lane_name(s: Shuttle) -> str:
    return "%s %d" % (LANE_NAME, s.index)


def _approach_name(s: Shuttle) -> str:
    return "%s %d" % (_APPROACH_POINT, s.index)


def _ring(index: int, a, b) -> tuple:
    """Shuttle `index`'s offset on a _RING_GU ring spanned by unit vectors
    `a` and `b`: ten points 31 GU apart."""
    t = 2.0 * math.pi * (index - 1) / COUNT
    c, s = _RING_GU * math.cos(t), _RING_GU * math.sin(t)
    return (c * a[0] + s * b[0], c * a[1] + s * b[1], c * a[2] + s * b[2])


def _xyz(p) -> tuple:
    return (p.x, p.y, p.z)


def _put_waypoint(pSet, set_name: str, name: str, at: tuple, fwd, up) -> None:
    import App
    wp = pSet.GetObject(name)
    if wp is None:
        wp = App.Waypoint_Create(name, set_name, None)
        if pSet.GetObject(name) is not wp:
            pSet.AddObjectToSet(wp, name)
        wp.SetStatic(1)
        wp.SetNavPoint(0)
    wp.SetTranslateXYZ(*at)
    wp.AlignToVectors(fwd, up)
    wp.Update(0)


def _anchor_pose(pSet, anchor_name: str):
    """World (location, rotation) of the region's home station: the station
    itself when the set holds it, else its placement point (the pose a
    rebuilt station gets), so a region built while the station is not
    standing still has lanes. None when neither is known."""
    station = pSet.GetObject(anchor_name)
    if station is not None:
        return station.GetWorldLocation(), station.GetWorldRotation()
    from engine.systems import home_stations
    for row in home_stations.stations_for_set(pSet.GetName()):
        if row.name == anchor_name:
            return home_stations.read_point(row, pSet)
    return None


def _lane_axis(pSet, set_name: str):
    """(origin, forward, side, up) the region's lane is laid along.

    Starbase 12: straight out of the bay, from "Docking Exit End" along the
    exit axis, so its centre is BEHIND a departing shuttle all the way out
    and BEYOND an arriving one's approach point. BC's Intercept steers round
    any ship over 150 GU in the way (AdjustDestinationForLargeObstacles,
    Intercept.py:286) and the station's radius is 296 GU live: a lane off
    the bay axis put the station ahead of the fly-out, Intercept moved its
    detour point every update, and the in-system warp chased it round the
    station forever (live 2026-10-26). Any other region, or a Starbase 12
    without its hardpoints (not standing): the home station's own forward.
    None when neither is known."""
    anchor_name = _ANCHORS.get(set_name)
    if set_name == HOME_SET:
        station = pSet.GetObject(anchor_name)
        if station is not None:
            try:
                pos, fwd, up = _hardpoint_world(station, "Docking Exit End")
            except AttributeError:
                pos = None
            if pos is not None:
                f, u = _xyz(fwd), _xyz(up)
                side = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2],
                        f[0] * u[1] - f[1] * u[0])
                return pos, fwd, side, up
    pose = _anchor_pose(pSet, anchor_name)
    if pose is None:
        return None
    loc, rot = pose
    return loc, rot.GetCol(1), _xyz(rot.GetCol(0)), rot.GetCol(2)


def _add_lane(pSet, set_name: str) -> None:
    """A waypoint LANE_GU out along the region's lane axis (_lane_axis),
    facing away from the station, and round it one point per shuttle (its
    arrival, departure and holding point). Never "Player Start"."""
    if _ANCHORS.get(set_name) is None or \
            pSet.GetObject(LANE_NAME) is not None:
        return
    axis = _lane_axis(pSet, set_name)
    if axis is None:
        return
    loc, fwd, side, up = axis
    centre = (loc.x + LANE_GU * fwd.x, loc.y + LANE_GU * fwd.y,
              loc.z + LANE_GU * fwd.z)
    for i in range(1, COUNT + 1):
        off = _ring(i, side, _xyz(up))
        _put_waypoint(pSet, set_name, "%s %d" % (LANE_NAME, i),
                      tuple(c + o for c, o in zip(centre, off)), fwd, up)
    _put_waypoint(pSet, set_name, LANE_NAME, centre, fwd, up)


def _both_regions():
    import App
    return (App.g_kSetManager.GetSet(HOME_SET), App.g_kSetManager.GetSet(FAR_SET))


def on_region_built(pSet, set_name: str) -> None:
    """Called by region_hooks after a region set is built. Adds the lane point;
    a Tau Ceti set built again while the service runs replaces the old set
    object, so the shuttles that were in the old one are docked."""
    if set_name not in _ANCHORS:
        return
    _add_lane(pSet, set_name)
    for s in _roster:
        if s.phase is Phase.DOCKED or s.ship is None:
            continue
        held = s.ship.GetContainingSet()
        if held is not pSet and held is not None \
                and held.GetName() == set_name:
            _dock(s)
    _start_if_ready()


def _start_if_ready() -> None:
    global _started
    if _started:
        return
    home, far = _both_regions()
    if home is None or far is None:
        return
    _started = True
    _restart()


def _restart() -> None:
    """Every shuttle docked, staggered one a minute from the first."""
    if not _roster:
        for i in range(1, COUNT + 1):
            _roster.append(Shuttle(index=i, name="SB12 Shuttle %d" % i))
    for s in _roster:
        if s.phase is Phase.LOST:
            continue
        if s.phase is not Phase.DOCKED:
            _dock(s)
        s.timer = (s.index - 1) * _STAGGER_S
        s.bearing_accum = 0.0
        s.dock_name = None


# ── Docking in and out of the world ──────────────────────────────────────────

def _stop_warp(ship) -> None:
    """Stop the NPC warp `ship` is flying, if any. With the renderer on, a
    warp is a flythrough: the ship waits in BC's "warp" set for the transit
    and a later step of its WarpSequence (_PlacePlayerAction) drops it into
    the destination set, whatever the AI or the service did meanwhile. The
    playing sequence is the one the ship's warp engine holds
    (WarpSequence.Play attaches it); Abort cancels its pending steps. The
    warp state goes back to not warping and any warp-in slide ends."""
    from engine.appc import warp, warp_state
    sub = ship.GetWarpEngineSubsystem()
    if not isinstance(sub, warp_state.WarpEngineSubsystem):
        return
    seq = sub.GetWarpSequence()
    if isinstance(seq, warp.WarpSequence) and seq.IsPlaying():
        seq.Abort()
    if sub.is_dewarp_driving():
        sub._end_dewarp_drive()
    warp_state.end_flythrough(ship)


def _remove_from_sets(ship) -> None:
    """Take `ship` out of every set that holds it (as _PlacePlayerAction
    does before it places a ship)."""
    import App
    for pSet in list(App.g_kSetManager.GetAllSets()):
        name = ship.GetName()
        if pSet.GetObject(name) is ship:
            pSet.RemoveObjectFromSet(name)


def _dock(shuttle: Shuttle) -> None:
    """Take the shuttle out of its set, drop its AI and stop any warp it is
    flying; it waits DOCK_S."""
    _release_bay(shuttle)
    _release_dock(shuttle)
    ship = shuttle.ship
    if ship is not None:
        _stop_warp(ship)
        pSet = ship.GetContainingSet()
        if pSet is not None:
            try:
                ship.ClearAI()
            except Exception:  # noqa: BLE001 - a dead ship has no AI to drop
                pass
            pSet.RemoveObjectFromSet(shuttle.name)
    shuttle.phase = Phase.DOCKED
    shuttle.timer = DOCK_S
    shuttle.dock_name = None
    shuttle.bearing_accum = 0.0
    shuttle.bearing_prev = None
    shuttle.ai = None
    shuttle.leg = None


def _home_station():
    """Starbase 12 if it is in its set and alive, else None."""
    import App
    pSet = App.g_kSetManager.GetSet(HOME_SET)
    station = None if pSet is None else pSet.GetObject(_ANCHORS[HOME_SET])
    if station is None or station.IsDead() or station.IsDying():
        return None
    return station


def _hardpoint_world(station, hardpoint: str):
    """World (location, forward, up) of one of the station's position /
    orientation hardpoints, the way DockWithStarbase.MakeWaypoints turns a
    bay point into a pose."""
    import MissionLib
    pos, fwd, up = MissionLib.GetPositionOrientationFromProperty(
        station, hardpoint)
    if None in (pos, fwd, up):
        raise AttributeError("%s has no position/orientation property (%s)"
                             % (station.GetName(), hardpoint))
    rot = station.GetWorldRotation()
    pos.MultMatrixLeft(rot)
    pos.Add(station.GetWorldLocation())
    fwd.MultMatrixLeft(rot)
    up.MultMatrixLeft(rot)
    return pos, fwd, up


def _bay_pose(station):
    """World (location, forward, up) of the station's "Docking Exit Start"."""
    return _hardpoint_world(station, _BAY_EXIT)


def _launch(shuttle: Shuttle) -> None:
    """Create (first time) or re-add the shuttle at Starbase 12's exit point
    and start the undock. No live Starbase 12: it stays docked."""
    station = _home_station()
    if station is None:
        return
    pSet = station.GetContainingSet()
    pos, fwd, up = _bay_pose(station)
    ship = shuttle.ship
    if ship is None:
        import loadspacehelper
        create = getattr(loadspacehelper.CreateShip,
                         "_dauntless_home_station_orig", loadspacehelper.CreateShip)
        ship = create(SCRIPT, pSet, shuttle.name, "", 0, 0)
        shuttle.ship = ship
        if ship is None:
            raise RuntimeError("CreateShip returned no ship")
        import App
        ship.AddPythonFuncHandlerForInstance(
            App.ET_OBJECT_EXPLODING, __name__ + ".ObjectExploding")
    elif pSet.GetObject(shuttle.name) is not ship:
        _remove_from_sets(ship)
        pSet.AddObjectToSet(ship, shuttle.name)
    ship.SetTranslate(pos)
    ship.AlignToVectors(fwd, up)
    ship.UpdateNodeOnly()
    owners.tag(ship, OWNER_NAME, shuttle.index)
    if _battle is not None:
        _battle.start.setdefault(shuttle.index, _conditions(ship))
    shuttle.bearing_accum = 0.0
    _enter(shuttle, Phase.UNDOCKING)


class _ShuttleOwner:
    """Registered so a battle restore knows these ships are the service's, not
    battle objects. The service restores them itself after a battle (install,
    controller ruling R1 option b): sim_restore never records them, so never
    asks for a rebuild."""
    name = OWNER_NAME
    restores_after_battle = True

    def rebuild(self, old, record):
        """Insurance, should a restore path ever ask: the shuttle whose
        current ship is `old` goes DOCKED and drops it (a fresh ship at its
        next launch). `old` is never re-added and nothing is built."""
        for s in _roster:
            if s.index == record.key and s.ship is old:
                _dock(s)
                s.ship = None
                s.killer = None
        return None

    def after_rebuild(self, new, record) -> None:
        pass


owners.register(_ShuttleOwner())


# ── Losses ───────────────────────────────────────────────────────────────────

def ObjectExploding(pObject, pEvent):
    """ET_OBJECT_EXPLODING on a shuttle (an instance handler, registered when
    the ship is built): remember who fired the blow that started its death.
    The death itself is ship_lifecycle's "destroyed", at the end of the
    throes, which carries no killer."""
    try:
        import App
        get = getattr(type(pEvent), "GetFiringPlayerID", None)
        fid = get(pEvent) if get is not None else App.NULL_ID
        killer = App.TGObject_GetTGObjectPtr(fid) if fid else None
        for s in _roster:
            if s.ship is pObject:
                s.killer = None if killer is None else killer.GetName()
    finally:
        pObject.CallNextHandler(pEvent)


def _game_time() -> float:
    import App
    return App.g_kUtopiaModule.GetGameTime()


def _lose(s: Shuttle) -> None:
    """The shuttle's ship died: LOST until reset(), the loss recorded."""
    ship = s.ship
    pSet = ship.GetContainingSet()
    _release_bay(s)
    _release_dock(s)
    s.phase = Phase.LOST
    s.ship = None
    s.ai = None
    s.leg = None
    s.held = False
    s.dock_name = None
    killer, s.killer = s.killer, None
    if _battle is not None:
        _battle.lost[s.index] = ship      # a battle loss is never recorded
        return
    _losses.append(Loss(index=s.index, name=s.name,
                        set_name="" if pSet is None else pSet.GetName(),
                        game_time=_game_time(), killer=killer))


def _on_lifecycle(event: str, ship) -> None:
    if event != "destroyed":
        return
    for s in _roster:
        if s.ship is ship and s.phase is not Phase.LOST:
            _lose(s)
            return


ship_lifecycle.subscribe(_on_lifecycle)


# ── Quick Battle ─────────────────────────────────────────────────────────────
# A battle is a simulation (spec §6): when it ends, every shuttle it damaged
# or destroyed comes back docked, wherever it was, and its losses are never
# recorded. The service does this itself; sim_restore leaves the shuttles out
# of its snapshot (the owner's `restores_after_battle`), which would rebuild a
# shuttle that merely moved on and leave two objects for one index.

# A subsystem this much below its battle-start condition was damaged.
_DAMAGE_TOLERANCE = 1e-6

_MARK = "_dauntless_shuttle_service_orig"


def _conditions(ship) -> list:
    from engine.appc.subsystems import iter_subsystems
    return [sub.GetCondition() for sub in iter_subsystems(ship)]


def _damaged(s: Shuttle, battle: _Battle) -> bool:
    """Any subsystem below its condition when the battle started (or when
    the shuttle launched during it). Shields are not damage: they recharge."""
    before = battle.start.get(s.index)
    if before is None or s.ship is None:
        return False
    now = _conditions(s.ship)
    return len(now) != len(before) or any(
        n < b - _DAMAGE_TOLERANCE for n, b in zip(now, before))


def _discard(ship, name: str) -> None:
    """Take a shuttle's old ship out of the world for good, as sim_restore
    does with an object it replaces: a fresh one is built at the next
    launch."""
    from engine.appc import ship_death
    from engine.appc.objects import broadcast_object_deleted
    ship_death.forget(ship)
    ship_death._clear_target_locks(ship)
    _stop_warp(ship)
    pSet = ship.GetContainingSet()
    if pSet is not None and pSet.GetObject(name) is ship:
        pSet.RemoveObjectFromSet(name)
    broadcast_object_deleted(ship)


def _battle_started() -> None:
    """A start with a battle already running (StartSimulation2 again, no End
    between) merges into it: the first start's conditions and the battle's
    losses so far are kept; only a shuttle not yet recorded is added."""
    global _battle
    if _battle is None:
        _battle = _Battle()
    for s in _roster:
        if s.ship is not None and s.phase is not Phase.LOST:
            _battle.start.setdefault(s.index, _conditions(s.ship))


def _battle_ended() -> None:
    """Every shuttle the battle destroyed or damaged goes docked, its old ship
    discarded; the rest carry on. Each shuttle has its own try."""
    global _battle
    battle, _battle = _battle, None
    if battle is None:
        return
    for s in _roster:
        try:
            if s.index in battle.lost:
                _discard(battle.lost[s.index], s.name)
                _dock(s)
            elif _damaged(s, battle):
                ship = s.ship
                _dock(s)
                _discard(ship, s.name)
                s.ship = None
                s.killer = None     # the discarded ship's, not the next one's
        except Exception as exc:  # noqa: BLE001 - the others still come back
            _park(s, exc)


def _chain(fn):
    """`fn`, then each function it wraps, following any `_dauntless_*_orig`
    link (ours or another module's)."""
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        yield fn
        links = getattr(fn, "__dict__", {})
        fn = next((v for k, v in links.items()
                   if k.startswith("_dauntless_") and k.endswith("_orig")),
                  None)


def _wrap(qb, name, make) -> bool:
    current = qb.__dict__.get(name)
    if current is None or any(_MARK in getattr(f, "__dict__", {})
                              for f in _chain(current)):
        return False
    wrapper = make(current)
    wrapper.__name__ = name
    setattr(wrapper, _MARK, current)
    setattr(qb, name, wrapper)
    return True


def _make_start(orig):
    def StartSimulation2(*args):
        global _battle
        fresh = _battle is None
        try:
            _battle_started()
        except Exception:  # noqa: BLE001 - never stop BC's start
            _log.exception("shuttles: noting the battle start failed")
        try:
            return orig(*args)
        except Exception:
            if fresh:
                _battle = None     # no battle started
            raise
    return StartSimulation2


def _make_end(orig):
    def EndSimulation(*args):
        try:
            return orig(*args)
        finally:
            try:
                _battle_ended()
            except Exception:  # noqa: BLE001 - never mask BC's end
                _log.exception("shuttles: restoring after the battle failed")
    return EndSimulation


def install(qb) -> bool:
    """Wrap the Quick Battle module's StartSimulation2 and EndSimulation (as
    sim_restore does: SDK callers reach them through the module global); True
    when this call added a wrapper. Never installs twice."""
    added = _wrap(qb, "StartSimulation2", _make_start)
    return _wrap(qb, "EndSimulation", _make_end) or added


# ── Bay points ───────────────────────────────────────────────────────────────

def _placement(pSet, name: str, speed: float):
    """Get or create the waypoint `name` in `pSet`, as
    DockWithStarbase.MakeWaypoints does: an existing one is reused."""
    import App
    wp = App.Waypoint_Cast(App.PlacementObject_GetObject(pSet, name))
    if wp is None:
        wp = App.Waypoint_Create(name, pSet.GetName(), None)
        wp.SetSpeed(speed)
    if pSet.GetObject(name) is not wp:
        pSet.AddObjectToSet(wp, name)
    return wp


def _place_from_hardpoint(wp, station, hardpoint: str,
                          back_gu: float = 0.0) -> None:
    """Pose `wp` at the station's hardpoint in world space, as
    DockWithStarbase.PositionObjectFromLocalInfo does, then `back_gu` back
    along the hardpoint's forward (negative: ahead of it)."""
    pos, fwd, up = _hardpoint_world(station, hardpoint)
    if back_gu:
        pos.SetXYZ(pos.x - back_gu * fwd.x, pos.y - back_gu * fwd.y,
                   pos.z - back_gu * fwd.z)
    wp.SetTranslate(pos)
    wp.AlignToVectors(fwd, up)
    wp.UpdateNodeOnly()


def _entry_points(station) -> None:
    """"Docking Entry" -> "Docking Entry End", built as MakeWaypoints builds
    them, the approach point _CLEAR_GU outside the bay mouth, and round it
    (square to the bay axis) one approach / holding point per shuttle."""
    pSet = station.GetContainingSet()
    start = _placement(pSet, _ENTRY, 5.0)
    end = _placement(pSet, _ENTRY_END, 2.0)
    nxt = start.GetNext()
    if nxt is None or nxt.GetObjID() != end.GetObjID():
        start.InsertAfterObj(end)
    _place_from_hardpoint(start, station, "Docking Entry Start")
    _place_from_hardpoint(end, station, "Docking Entry End")
    centre = _placement(pSet, _APPROACH_POINT, 4.0)
    _place_from_hardpoint(centre, station, "Docking Entry Start", _CLEAR_GU)
    _pos, fwd, up = _hardpoint_world(station, "Docking Entry Start")
    f, u = _xyz(fwd), _xyz(up)
    side = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2],
            f[0] * u[1] - f[1] * u[0])
    c = _xyz(centre.GetWorldLocation())
    for i in range(1, COUNT + 1):
        wp = _placement(pSet, "%s %d" % (_APPROACH_POINT, i), 4.0)
        off = _ring(i, u, side)
        wp.SetTranslateXYZ(c[0] + off[0], c[1] + off[1], c[2] + off[2])
        wp.AlignToVectors(fwd, up)
        wp.UpdateNodeOnly()


def _exit_point(station) -> None:
    """The clearance point _CLEAR_GU beyond "Docking Exit End"."""
    _place_from_hardpoint(
        _placement(station.GetContainingSet(), _EXIT_POINT, 4.0), station,
        "Docking Exit End", -_CLEAR_GU)


# ── Legs ─────────────────────────────────────────────────────────────────────

def _hold_bay(shuttle: Shuttle, station) -> None:
    """Collisions between the shuttle and the station off (a bay leg)."""
    if shuttle.bay_station is not None and shuttle.bay_station is not station:
        _release_bay(shuttle)
    shuttle.ship.EnableCollisionsWith(station, 0)
    shuttle.bay_station = station


def _release_bay(shuttle: Shuttle) -> None:
    """Collisions with the bay leg's station back on."""
    station, shuttle.bay_station = shuttle.bay_station, None
    if station is not None and shuttle.ship is not None:
        shuttle.ship.EnableCollisionsWith(station, 1)


def _mask_dock(shuttle: Shuttle, dock) -> None:
    """Collisions between the shuttle and the dry dock it flies to and
    circles off, so the AvoidObstacles preprocessor (which reads the same
    per-pair mask) never steers it away from its own dock."""
    if shuttle.dock_mask is not dock:
        _release_dock(shuttle)
    shuttle.ship.EnableCollisionsWith(dock, 0)
    shuttle.dock_mask = dock


def _release_dock(shuttle: Shuttle) -> None:
    """Collisions with the dry dock back on."""
    dock, shuttle.dock_mask = shuttle.dock_mask, None
    if dock is not None and shuttle.ship is not None:
        shuttle.ship.EnableCollisionsWith(dock, 1)


def _avoiding(ship, ai):
    """`ai` inside BC's AvoidObstacles preprocessor, built as the SDK's own
    compound AIs build it (E1M1_AI_Shuttle1.py; the engine binds its port,
    engine/appc/collision_avoidance.py, in place of the Python class).
    Controller ruling R10: every open-space leg and hold avoids obstacles;
    the bay and circling legs do not (the target station's collision mask
    keeps it out of the scan where a wrapped leg flies at it). Finishes
    when `ai` does."""
    import App
    import AI.Preprocessors
    pre = App.PreprocessingAI_Create(ship, "SB12ShuttleAvoid")
    pre.SetInterruptable(1)
    pre.SetPreprocessingMethod(AI.Preprocessors.AvoidObstacles(), "Update")
    pre.SetContainedAI(ai)
    return pre


def _give_ai(shuttle: Shuttle, ai) -> None:
    """Hand the ship this leg's AI (None: no AI) and remember the leg."""
    if ai is None:
        shuttle.ship.ClearAI()
    else:
        shuttle.ship.SetAI(ai)
    shuttle.ai = ai
    shuttle.leg = shuttle.phase
    shuttle.held = False


def _leg_done(shuttle: Shuttle) -> bool:
    """The leg's AI finished: the AI driver clears a finished tree."""
    return shuttle.ship.GetAI() is not shuttle.ai


def _plain(ship, name: str, module: str):
    import App
    ai = App.PlainAI_Create(ship, name)
    ai.SetScriptModule(module)
    ai.SetInterruptable(1)
    return ai


def _intercept(ship, target: str, distance: float = _POINT_GU):
    ai = _plain(ship, "SB12ShuttleIntercept", "Intercept")
    script = ai.GetScriptInstance()
    script.SetTargetObjectName(target)
    script.SetInterceptDistance(distance)
    script.SetInSystemWarpDistance(_IN_SYSTEM_WARP_GU)
    return ai


def _follow(ship, waypoint: str):
    ai = _plain(ship, "SB12ShuttleWaypoints", "FollowWaypoints")
    ai.GetScriptInstance().SetTargetWaypointName(waypoint)
    return ai


def _start_undocking(s: Shuttle) -> None:
    import App
    import AI.Compound.UndockFromStarbase as undock
    station = _home_station()
    if station is None:
        raise RuntimeError("no Starbase 12 to undock from")
    undock_ai = undock.CreateAI(s.ship, station)
    if undock_ai is None:
        raise RuntimeError("Starbase 12 has no docking exit")
    _exit_point(station)
    seq = App.SequenceAI_Create(s.ship, "SB12ShuttleUndock")
    seq.SetInterruptable(1)
    seq.SetLoopCount(1)
    seq.SetResetIfInterrupted(1)
    seq.SetDoubleCheckAllDone(0)
    seq.SetSkipDormant(0)
    seq.AddAI(undock_ai)
    seq.AddAI(_follow(s.ship, _EXIT_POINT))
    _hold_bay(s, station)
    _give_ai(s, seq)


def _round_point(s: Shuttle):
    """The name of the waypoint a departing shuttle flies round Starbase 12
    by, or None when the station is not between it and its lane (the usual
    case: it leaves the bay along the bay axis, the station behind it)."""
    import App
    station = _home_station()
    pSet = App.g_kSetManager.GetSet(HOME_SET)
    lane = None if pSet is None else pSet.GetObject(_lane_name(s))
    if station is None or lane is None or \
            s.ship.GetContainingSet() is not pSet:
        return None
    p = _xyz(s.ship.GetWorldLocation())
    c = _xyz(station.GetWorldLocation())
    q = _xyz(lane.GetWorldLocation())
    ahead = sum((ci - pi) * (qi - pi) for ci, pi, qi in zip(c, p, q))
    if ahead <= 0.0:
        return None
    axis = _lane_axis(pSet, HOME_SET)
    if axis is None:
        return None
    _origin, fwd, side, up = axis
    sign = 1.0 if sum((pi - ci) * bi
                      for pi, ci, bi in zip(p, c, side)) >= 0.0 else -1.0
    r = max(station.GetRadius(), _STATION_CLEAR_GU) + _ROUND_MARGIN_GU
    wp = _placement(pSet, _ROUND_POINT, 4.0)
    wp.SetTranslateXYZ(*(ci + sign * r * bi for ci, bi in zip(c, side)))
    wp.AlignToVectors(fwd, up)
    wp.UpdateNodeOnly()
    return _ROUND_POINT


def _start_departing(s: Shuttle) -> None:
    import App
    out = _avoiding(s.ship, _intercept(s.ship, _lane_name(s)))
    round_point = _round_point(s)
    if round_point is None:
        _give_ai(s, out)
        return
    seq = App.SequenceAI_Create(s.ship, "SB12ShuttleRound")
    seq.SetInterruptable(1)
    seq.SetLoopCount(1)
    seq.SetResetIfInterrupted(1)
    seq.SetDoubleCheckAllDone(0)
    seq.SetSkipDormant(0)
    seq.AddAI(_follow(s.ship, round_point))
    seq.AddAI(out)
    _give_ai(s, seq)


def _warp_to(s: Shuttle, module: str) -> None:
    """BC's Warp to the shuttle's own lane point in region `module`."""
    ai = _plain(s.ship, "SB12ShuttleWarp", "Warp")
    script = ai.GetScriptInstance()
    script.SetDestinationSetName(module)
    script.SetDestinationPlacementName(_lane_name(s))
    _give_ai(s, ai)


def _start_warping_out(s: Shuttle) -> None:
    _warp_to(s, "Systems.DryDock.DryDock")


def _standing_stations() -> dict:
    """Name -> object for every home station in DryDock that is standing,
    in the set and alive (the dry docks and the Station)."""
    import App
    from engine.systems import home_stations
    pSet = App.g_kSetManager.GetSet(FAR_SET)
    found = {}
    if pSet is None:
        return found
    for row in home_stations.stations_for_set(FAR_SET):
        if not home_stations.is_standing(row):
            continue
        obj = pSet.GetObject(row.name)
        if obj is not None and not obj.IsDead() and not obj.IsDying():
            found[row.name] = obj
    return found


def _dry_dock(name):
    """The named dry dock if it is a standing home station, in DryDock and
    alive, else None."""
    return _standing_stations().get(name) if name in _DRY_DOCKS else None


def _hull_radius(obj) -> float:
    """The larger of the object's bound (0 headless) and its hardpoint hull
    radius."""
    hull = obj.GetHull()
    return max(obj.GetRadius(), 0.0 if hull is None else hull.GetRadius())


def _bands(dock_name) -> list:
    """The dock's orbit bands, (near, far) innermost first (see
    _ORBIT_FLOOR_GU): disjoint, and none reaching half way to another
    standing station. Empty for a dock that is not standing."""
    stations = _standing_stations()
    dock = stations.get(dock_name)
    if dock is None or dock_name not in _DRY_DOCKS:
        return []
    at = _xyz(dock.GetWorldLocation())
    gaps = [math.dist(at, _xyz(o.GetWorldLocation()))
            for n, o in stations.items() if n != dock_name]
    cap = min(gaps) / 2.0 - _ORBIT_CAP_MARGIN_GU if gaps else math.inf
    near = max(2.0 * _hull_radius(dock), _ORBIT_FLOOR_GU) + _BAND_INSET_GU
    bands = []
    while len(bands) < COUNT and near + _BAND_GU <= cap:
        bands.append((near, near + _BAND_GU))
        near += _BAND_GU + _BAND_GAP_GU
    return bands


def _bound_for(name, s: Shuttle) -> list:
    """The other shuttles flying to or circling dock `name`."""
    return [o for o in _roster if o is not s and o.dock_name == name
            and o.phase in (Phase.TO_DOCK, Phase.CIRCLING)]


def _leaving_near(name, s: Shuttle) -> bool:
    """Another shuttle that left dock `name` is still near it, on its way
    out along the corridor towards the lane."""
    dock = _dry_dock(name)
    return dock is not None and any(
        o is not s and o.phase is Phase.LEAVING_DOCKS and o.dock_name == name
        and o.ship is not None and _distance(o.ship, dock) < _DOCK_CLEAR_GU
        for o in _roster)


def _done_circling(o: Shuttle) -> bool:
    return o.phase is Phase.CIRCLING and \
        o.bearing_accum >= CIRCLES * 2.0 * math.pi


def _free_orbit(name, s: Shuttle):
    """The orbit `s` may take at dock `name`, or None. Orbits fill outwards
    and empty inwards, so no shuttle ever crosses another's orbit: a newcomer
    takes the orbit outside every occupied one, if the dock has it, and only
    while nobody is flying in to or out from that dock (they share the
    corridor towards the lane) or waiting there to leave."""
    others = _bound_for(name, s)
    if (any(o.phase is Phase.TO_DOCK or _done_circling(o) for o in others)
            or _leaving_near(name, s)):
        return None
    k = 1 + max((o.orbit_slot for o in others), default=-1)
    return k if k < len(_bands(name)) else None


def _may_leave(s: Shuttle) -> bool:
    """Only the outermost shuttle at a dock leaves, and only while nobody is
    flying in to or out from it."""
    return (all(o.phase is Phase.CIRCLING and o.orbit_slot < s.orbit_slot
                for o in _bound_for(s.dock_name, s))
            and not _leaving_near(s.dock_name, s))


def _start_to_dock(s: Shuttle) -> None:
    """Fly to a random standing dry dock with a free orbit, one of those the
    fewest other shuttles are bound for; the intercept stops at the orbit's
    outer edge. None standing: leave. None with a free orbit: hold at the
    shuttle's own lane point until one frees."""
    s.dock_name = None
    _release_dock(s)
    standing = [n for n in _DRY_DOCKS if _dry_dock(n) is not None]
    if not standing:
        _enter(s, Phase.LEAVING_DOCKS)
        return
    free = {}
    for n in standing:
        k = _free_orbit(n, s)
        if k is not None:
            free[n] = k
    if not free:
        _give_ai(s, _avoiding(s.ship, _intercept(s.ship, _lane_name(s))))
        s.held = True
        return
    count = {n: len(_bound_for(n, s)) for n in free}
    fewest = min(count.values())
    s.dock_name = _rng.choice([n for n in free if count[n] == fewest])
    s.orbit_slot = free[s.dock_name]
    far = _bands(s.dock_name)[s.orbit_slot][1]
    _mask_dock(s, _dry_dock(s.dock_name))
    _give_ai(s, _avoiding(s.ship, _intercept(s.ship, s.dock_name, far)))


def _orbit_gone(s: Shuttle) -> bool:
    """The shuttle's orbit no longer exists: the dock's bands shrank (a
    neighbouring station came back to standing)."""
    return s.orbit_slot >= len(_bands(s.dock_name))


def _start_circling(s: Shuttle) -> None:
    import App
    if _orbit_gone(s):
        _enter(s, Phase.TO_DOCK)            # choose again
        return
    near, far = _bands(s.dock_name)[s.orbit_slot]
    ai = _plain(s.ship, "SB12ShuttleCircle", "CircleObject")
    script = ai.GetScriptInstance()
    script.SetFollowObjectName(s.dock_name)
    # E1M1's shuttles circle with their left side to the station.
    script.SetNearFacingVector(App.TGPoint3_GetModelLeft())
    script.SetRoughDistances(near, far)
    _give_ai(s, ai)


def _start_leaving_docks(s: Shuttle) -> None:
    _release_dock(s)
    _give_ai(s, _avoiding(s.ship, _intercept(s.ship, _lane_name(s))))


def _start_warping_back(s: Shuttle) -> None:
    _warp_to(s, "Systems.Starbase12.Starbase12")


def _start_approaching(s: Shuttle) -> None:
    station = _home_station()
    if station is None:
        _enter(s, Phase.WAITING)
        return
    _entry_points(station)
    _give_ai(s, _avoiding(s.ship, _intercept(s.ship, _approach_name(s))))


def _start_entering(s: Shuttle) -> None:
    """From the shuttle's own approach point to the shared one on the bay
    axis, then the bay waypoints (one shuttle in the bay at a time)."""
    import App
    station = _home_station()
    if station is None:
        _enter(s, Phase.WAITING)
        return
    _entry_points(station)
    seq = App.SequenceAI_Create(s.ship, "SB12ShuttleEnter")
    seq.SetInterruptable(1)
    seq.SetLoopCount(1)
    seq.SetResetIfInterrupted(1)
    seq.SetDoubleCheckAllDone(0)
    seq.SetSkipDormant(0)
    seq.AddAI(_follow(s.ship, _APPROACH_POINT))
    seq.AddAI(_follow(s.ship, _ENTRY))
    _hold_bay(s, station)
    _give_ai(s, seq)


def _start_waiting(s: Shuttle) -> None:
    _release_bay(s)
    _give_ai(s, _avoiding(s.ship, _intercept(s.ship, _lane_name(s))))


_STARTS = {
    Phase.UNDOCKING: _start_undocking,
    Phase.DEPARTING: _start_departing,
    Phase.WARPING_OUT: _start_warping_out,
    Phase.TO_DOCK: _start_to_dock,
    Phase.CIRCLING: _start_circling,
    Phase.LEAVING_DOCKS: _start_leaving_docks,
    Phase.WARPING_BACK: _start_warping_back,
    Phase.APPROACHING: _start_approaching,
    Phase.ENTERING: _start_entering,
    Phase.WAITING: _start_waiting,
}


def _enter(shuttle: Shuttle, phase: Phase) -> None:
    """Move to `phase` and start its leg."""
    shuttle.phase = phase
    start = _STARTS.get(phase)
    if start is not None:
        start(shuttle)


def _distance(a, b) -> float:
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    return ((pa.x - pb.x) ** 2 + (pa.y - pb.y) ** 2
            + (pa.z - pb.z) ** 2) ** 0.5


def _pushed_from_bay(s: Shuttle) -> bool:
    """The undocking shuttle is farther than _PUSHED_GU from the bay mouth
    ("Docking Exit End", 2.3 GU from "Docking Entry"): BC's player docking
    moved it (it clears 300 GU round "Docking Entry"). Its own leg never
    takes it past ~160 GU (the exit point is _CLEAR_GU beyond the mouth)."""
    pSet = s.ship.GetContainingSet()
    mouth = None if pSet is None else pSet.GetObject("Docking Exit End")
    return mouth is not None and _distance(s.ship, mouth) > _PUSHED_GU


def _check_undocking(s: Shuttle) -> None:
    if _leg_done(s):
        _release_bay(s)
        _enter(s, Phase.DEPARTING)
    elif _bay_busy or _pushed_from_bay(s):
        # The player has taken the bay, or pushed the shuttle out of it:
        # following the bay waypoints would fly it back in through the
        # docking player. It departs from where it is; collisions with the
        # station stay off until it is clear of it (_check_departing).
        _enter(s, Phase.DEPARTING)


def _check_departing(s: Shuttle) -> None:
    if s.bay_station is not None and \
            _distance(s.ship, s.bay_station) > _STATION_CLEAR_GU:
        _release_bay(s)
    if _leg_done(s):
        _release_bay(s)
        _enter(s, Phase.WARPING_OUT)


def _check_warp(s: Shuttle, src: str, dest: str, arrived: Phase,
                retry: Phase) -> None:
    """A warp leg from region `src` to `dest`: done once in `dest` and out of
    warp. The Warp AI finished or dropped while still in `src` (a refused
    warp): fly back to the lane (`retry`) and try again."""
    from engine.appc import warp_state
    pSet = s.ship.GetContainingSet()
    if (pSet is None or warp_state.is_ship_warping(s.ship)
            or warp_state.is_arriving(s.ship)):
        return
    if pSet.GetName() == dest:
        _enter(s, arrived)
    elif pSet.GetName() == src and _leg_done(s):
        _enter(s, retry)


def _check_warping_out(s: Shuttle) -> None:
    _check_warp(s, HOME_SET, FAR_SET, Phase.TO_DOCK, Phase.DEPARTING)


def _check_warping_back(s: Shuttle) -> None:
    _check_warp(s, FAR_SET, HOME_SET, Phase.APPROACHING, Phase.LEAVING_DOCKS)


def _check_to_dock(s: Shuttle) -> None:
    if s.dock_name is None:
        # Holding at its lane point for a free orbit.
        standing = [n for n in _DRY_DOCKS if _dry_dock(n) is not None]
        if not standing or any(_free_orbit(n, s) is not None
                               for n in standing):
            _enter(s, Phase.TO_DOCK)        # choose (or leave: none standing)
        elif _leg_done(s):
            _give_ai(s, _avoiding(s.ship,
                                  _plain(s.ship, "SB12ShuttleHold", "Stay")))
            s.held = True
    elif _dry_dock(s.dock_name) is None:
        _enter(s, Phase.TO_DOCK)            # destroyed or gone: choose again
    elif _leg_done(s):
        s.bearing_accum = 0.0
        s.bearing_prev = None
        s.leave_at = CIRCLES * 2.0 * math.pi
        _enter(s, Phase.CIRCLING)


def _radial(ship, dock):
    """Dock -> ship, in the dock's frame."""
    a, b, rot = ship.GetWorldLocation(), dock.GetWorldLocation(), \
        dock.GetWorldRotation()
    d = (a.x - b.x, a.y - b.y, a.z - b.z)
    return tuple(d[0] * c.x + d[1] * c.y + d[2] * c.z
                 for c in (rot.GetCol(0), rot.GetCol(1), rot.GetCol(2)))


def _turned(a, b) -> float:
    """The angle between directions `a` and `b`, 0..pi."""
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
             a[0] * b[1] - a[1] * b[0])
    return math.atan2(math.sqrt(sum(c * c for c in cross)),
                      sum(x * y for x, y in zip(a, b)))


def _check_circling(s: Shuttle) -> None:
    dock = _dry_dock(s.dock_name)
    if dock is None or _orbit_gone(s):
        _enter(s, Phase.TO_DOCK)            # destroyed, gone or no orbit
        return
    # The bearing change is the angle the dock -> shuttle direction turned
    # this tick, not a planar atan2: CircleObject's orbit plane follows the
    # shuttle's approach and can stand nearly on edge to the dock's XY plane
    # (measured round Dry Dock2), where a planar bearing degenerates.
    radial = _radial(s.ship, dock)
    if s.bearing_prev is not None:
        s.bearing_accum += _turned(s.bearing_prev, radial)
    s.bearing_prev = radial
    if s.bearing_accum >= s.leave_at:
        # Back where it started circling (on the lane side) after whole
        # turns. Not the outermost, or the corridor is in use: one more turn.
        if _may_leave(s):
            _enter(s, Phase.LEAVING_DOCKS)
        else:
            s.leave_at += 2.0 * math.pi
    elif _leg_done(s):
        _enter(s, Phase.CIRCLING)           # AI dropped: circle on, count kept


def _check_leaving_docks(s: Shuttle) -> None:
    if _leg_done(s):
        _enter(s, Phase.WARPING_BACK)


def _hold(s: Shuttle) -> None:
    """Wait at the shuttle's own point outside the bay while the bay is the
    player's or another shuttle's, collisions with the station back on."""
    _release_bay(s)
    _give_ai(s, _avoiding(s.ship, _plain(s.ship, "SB12ShuttleHold", "Stay")))
    s.held = True


def _bay_free(s: Shuttle) -> bool:
    """The bay is neither the player's nor another shuttle's (ENTERING or
    UNDOCKING): one shuttle in the bay at a time."""
    return not _bay_busy and not any(
        o is not s and o.phase in (Phase.ENTERING, Phase.UNDOCKING)
        for o in _roster)


def _arrival_held() -> bool:
    """A shuttle holds outside the bay, waiting to enter."""
    return any(o.phase is Phase.APPROACHING and o.held for o in _roster)


def _check_approaching(s: Shuttle) -> None:
    if _home_station() is None:
        _enter(s, Phase.WAITING)
    elif s.held:
        if _bay_free(s):
            _enter(s, Phase.ENTERING)
    elif _leg_done(s):
        if _bay_free(s):
            _enter(s, Phase.ENTERING)
        else:
            _hold(s)


def _check_entering(s: Shuttle) -> None:
    if _home_station() is None:
        _enter(s, Phase.WAITING)
        return
    if _bay_busy:
        # The player has taken the bay: back out to the clearance point and
        # hold there (collisions stay off until the shuttle is clear).
        _enter(s, Phase.APPROACHING)
        return
    pSet = s.ship.GetContainingSet()
    entry = None if pSet is None else pSet.GetObject(_ENTRY)
    end = None if pSet is None else pSet.GetObject(_ENTRY_END)
    if entry is None or end is None or _distance(s.ship, entry) > _PUSHED_GU:
        # Moved off the bay path: approach again. Still the bay leg, so
        # collisions with the station stay off until it docks.
        _enter(s, Phase.APPROACHING)
    elif _leg_done(s):
        if _distance(s.ship, end) <= _DOCKED_GU:
            _dock(s)
        else:
            _enter(s, Phase.APPROACHING)


def _check_waiting(s: Shuttle) -> None:
    if _home_station() is not None:
        _enter(s, Phase.APPROACHING)
    elif _leg_done(s):
        _give_ai(s, _avoiding(s.ship, _plain(s.ship, "SB12ShuttleWait", "Stay")))


_CHECKS = {
    Phase.UNDOCKING: _check_undocking,
    Phase.DEPARTING: _check_departing,
    Phase.WARPING_OUT: _check_warping_out,
    Phase.TO_DOCK: _check_to_dock,
    Phase.CIRCLING: _check_circling,
    Phase.LEAVING_DOCKS: _check_leaving_docks,
    Phase.WARPING_BACK: _check_warping_back,
    Phase.APPROACHING: _check_approaching,
    Phase.ENTERING: _check_entering,
    Phase.WAITING: _check_waiting,
}


# ── The tick ─────────────────────────────────────────────────────────────────

def _player_presence():
    """True in Tau Ceti, False in any other system, None when it cannot be
    told: no live player, or the player in the warp transit set."""
    import App
    from engine.appc.warp import _WARP_TRANSIT_SET_NAME
    game = App.Game_GetCurrentGame()
    player = None if game is None else game.GetPlayer()
    pSet = None if player is None else player.GetContainingSet()
    if pSet is None or pSet.GetName() == _WARP_TRANSIT_SET_NAME:
        return None
    from engine.appc.sector_model import system_id_for_set
    return system_id_for_set(pSet.GetName()) == SYSTEM_ID


def _excluded_mission() -> bool:
    """The current mission is one the service stays out of: the module the
    mission was loaded from (Mission._module_name, as mission_change reads
    it) is in _EXCLUDED_MISSIONS."""
    import App
    game = App.Game_GetCurrentGame()
    episode = None if game is None else game.GetCurrentEpisode()
    mission = None if episode is None else episode.GetCurrentMission()
    name = None if mission is None else mission.__dict__.get("_module_name")
    return name in _EXCLUDED_MISSIONS


def _docking_tree(ai) -> bool:
    """`ai`'s tree was built by AI.Compound.DockWithStarbase or
    UndockFromStarbase: both run their steps as RunScript PlainAIs whose
    script module is the compound module itself (`SetScriptModule(__name__)`),
    the only thing a tree records about who built it. DockWithStarbase's one
    tree spans the approach, the docked wait and the undock; it is replaced
    (FlyForward) only once the ship is out."""
    from engine.appc.ai import PlainAI
    if ai is None:
        return False
    for node in ai.GetAllAIsInTree():
        if not isinstance(node, PlainAI) or node.GetScriptModule() != "RunScript":
            continue
        script = node.__dict__.get("_script_instance")
        module = None if script is None else script.__dict__.get("sModuleName")
        if isinstance(module, str) and \
                module.rsplit(".", 1)[-1] in _BAY_AI_MODULES:
            return True
    return False


def _player_owns_bay() -> bool:
    """Whether the player is docking at, docked in or undocking from Starbase
    12: in its set and either flying a docking/undocking tree or within
    _BAY_NEAR_GU of the bay mouth."""
    import App
    game = App.Game_GetCurrentGame()
    player = None if game is None else game.GetPlayer()
    pSet = None if player is None else player.GetContainingSet()
    if pSet is None or pSet.GetName() != HOME_SET:
        return False
    if _docking_tree(player.GetAI()):
        return True
    mouth = pSet.GetObject(_ENTRY)
    if mouth is not None:
        loc = mouth.GetWorldLocation()
    else:
        station = pSet.GetObject(_ANCHORS[HOME_SET])
        if station is None:
            return False
        loc = _hardpoint_world(station, "Docking Entry Start")[0]
    p = player.GetWorldLocation()
    return ((p.x - loc.x) ** 2 + (p.y - loc.y) ** 2 + (p.z - loc.z) ** 2
            <= _BAY_NEAR_GU * _BAY_NEAR_GU)


def _forget_restore_records() -> None:
    """Take every shuttle out of BC's docking restore record.
    DockWithStarbase.SetupDockPositions records, by ObjID, each object it
    pushes from inside the starbase in g_kRestoreTranslateDict, and
    FinishedUndocking teleports it back there minutes later: a shuttle long
    gone on its way (or docked, or in another set) would jump into the bay.
    Only a module BC has loaded is touched; the scale record holds only the
    docking ship itself."""
    import sys
    dock = sys.modules.get("AI.Compound.DockWithStarbase")
    record = None if dock is None else getattr(dock, "g_kRestoreTranslateDict",
                                               None)
    if not record:
        return
    ids = {s.ship.GetObjID() for s in _roster if s.ship is not None}
    for pushed in record.values():
        if isinstance(pushed, dict):
            for obj_id in ids.intersection(pushed):
                del pushed[obj_id]


def _in_the_world(ship) -> bool:
    """The ship is in a set the set manager still holds."""
    import App
    pSet = ship.GetContainingSet()
    return pSet is not None and any(
        x is pSet for x in App.g_kSetManager.GetAllSets())


def _step(s: Shuttle, dt: float) -> None:
    if s.phase is Phase.DOCKED:
        s.timer -= dt
        if s.timer <= 0.0 and _bay_free(s) and not _arrival_held():
            # A due shuttle waits docked while the bay is the player's or
            # another shuttle's, and while an arrival holds outside it
            # (arrivals first: else a launch can take the bay the tick it
            # frees, before the arrival checked earlier in the tick sees it).
            _launch(s)
        return
    check = _CHECKS.get(s.phase)
    if check is None:
        return
    from engine.appc import ship_death
    if ship_death._out_of_action(s.ship):
        return                  # dying: ship_lifecycle's "destroyed" ends it
    if not _in_the_world(s.ship):
        _dock(s)                # its set was deleted (E8M2 deletes Starbase12)
        return
    if s.bay_station is not None:
        station = _home_station()
        if station is not None and station is not s.bay_station:
            _hold_bay(s, station)       # Starbase 12 rebuilt: a new ObjID
    if s.leg is not s.phase:
        # Put into this phase from outside (a hand-over): start its leg.
        _enter(s, s.phase)
    else:
        check(s)


def _park(s: Shuttle, exc) -> None:
    """One line, then the shuttle waits a full dock period instead of failing
    again every tick."""
    print(f"[shuttles] {s.name} not launched: {type(exc).__name__}: {exc}",
          flush=True)
    try:
        _dock(s)
    except Exception:  # noqa: BLE001 - parking must not raise either
        s.phase = Phase.DOCKED
        s.timer = DOCK_S


def tick(dt: float) -> None:
    """Never raises: it runs inside the unguarded GameLoop.tick.

    Pause rule: only a player in a system other than Tau Ceti, or an
    excluded mission (_EXCLUDED_MISSIONS), pauses the service; no live
    player, or the warp transit set, leaves it as it is."""
    global _away, _bay_busy
    if not _enabled:
        return
    try:
        if not _started:
            _start_if_ready()
            if not _started:
                return
        present = False if _excluded_mission() else _player_presence()
        if present is None:
            return
        if not present:
            if not _away:
                _away = True
                for s in _roster:
                    if s.phase not in (Phase.DOCKED, Phase.LOST):
                        _dock(s)
            return
        if _away:
            _away = False
            _restart()
        _bay_busy = _player_owns_bay()
        if _bay_busy:
            _forget_restore_records()
    except Exception as exc:  # noqa: BLE001 - the loop must keep running
        # A persistent failure prints once; varying ones at most
        # _TICK_ERRORS_MAX times in all.
        msg = f"[shuttles] tick failed: {type(exc).__name__}: {str(exc)[:120]}"
        if msg not in _tick_errors and len(_tick_errors) < _TICK_ERRORS_MAX:
            _tick_errors.add(msg)
            print(msg, flush=True)
        return
    for s in _roster:
        try:
            _step(s, dt)
        except Exception as exc:  # noqa: BLE001 - one shuttle must not stop the rest
            _park(s, exc)
