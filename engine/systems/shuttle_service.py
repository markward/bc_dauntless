"""The Tau Ceti shuttle service: ten Federation shuttles between Starbase 12
and the Dry Docks.

A shuttle is a record, not a world object, while it is docked: it is in no set
and costs nothing. `_launch` puts it into the Starbase 12 set at the bay's
"Docking Exit Start"; `_dock` takes it out again. The service runs in every
game mode, belongs to no mission group, and pauses (every shuttle docked,
timers frozen) while the player is in another system. Away rule: only a player
in a system other than Tau Ceti pauses it; no live player, or the player in the
warp transit set, leaves it exactly as it is.

Each flying phase is one leg: `_enter` sets the phase and hands the ship the
leg's AI (`_give_ai`); a leg ends when that AI reports done (the AI driver
clears a finished tree) or the leg's own completion test holds. The Starbase
12 legs:

- UNDOCKING: BC's AI.Compound.UndockFromStarbase, then out along the bay axis
  to a clearance point beyond "Docking Exit End".
- DEPARTING: intercept to the region's lane point.
- WARPING_OUT: BC's Warp to the Dry Docks lane point; done once in DryDock
  and out of warp.
- APPROACHING: intercept to a clearance point outside the bay mouth.
- ENTERING: FollowWaypoints "Docking Entry" -> "Docking Entry End" (built the
  way DockWithStarbase.MakeWaypoints builds them), then docked.
- WAITING: Starbase 12 missing or dead; hold at the lane point until it is
  back.

Collisions with Starbase 12 are off on the bay legs (UNDOCKING, ENTERING) and
back on after. AI.Compound.DockWithStarbase itself is never used: it takes
the player's camera and starts a cutscene.

The Dry Docks legs (TO_DOCK onward) are not driven yet: a shuttle reaching
TO_DOCK docks on its next tick.
"""
from __future__ import annotations

import enum
import random
from dataclasses import dataclass

from engine.systems import owners

COUNT = 10
DOCK_S = 600.0
CIRCLES = 2
LANE_GU = 2000.0
LANE_NAME = "TC Shuttle Lane"
OWNER_NAME = "tau_ceti_shuttles"
SCRIPT = "Shuttle"
SYSTEM_ID = "tauceti"
HOME_SET = "Starbase12"
FAR_SET = "DryDock"
# set name -> the home station its lane point is measured from
_ANCHORS = {HOME_SET: "Starbase 12", FAR_SET: "Dry Dock"}
_BAY_EXIT = "Docking Exit Start"
_STAGGER_S = 60.0
# Intercepts to a lane or the approach point.
_INTERCEPT_GU = 100.0
_IN_SYSTEM_WARP_GU = 150.0
# Clearance points, this far out along the bay axis from the bay mouth. The
# bay is a radial slot 68-108 GU from Starbase 12's centre and the hull's
# bound is ~150 GU, while the lane point lies along the station's forward,
# not the bay's: a straight line between the bay and the lane would cut
# through the hull. So a shuttle leaves and arrives on the bay axis.
_CLEAR_GU = 150.0
_EXIT_POINT = "TC Shuttle Exit"
_APPROACH_POINT = "TC Shuttle Approach"
_ENTRY = "Docking Entry"
_ENTRY_END = "Docking Entry End"
# An ENTERING shuttle farther than this from "Docking Entry" was moved off the
# bay path (BC's player docking clears 300 GU round it): it approaches again.
# The approach always ends within _INTERCEPT_GU + _CLEAR_GU of it.
_PUSHED_GU = _INTERCEPT_GU + _CLEAR_GU + 25.0
# FollowWaypoints is done within 8 GU of its last waypoint.
_DOCKED_GU = 20.0


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
    ai: object = None            # the AI the current leg gave the ship
    leg: Phase | None = None     # the phase `ai` was given for
    bay_station: object = None   # collisions with it are off (a bay leg)


_roster: list = []
_started = False
_away = False
_rng = random.Random()
_tick_errors: set = set()


def roster() -> list:
    return _roster


def set_rng(rng: random.Random) -> None:
    global _rng
    _rng = rng


def reset() -> None:
    """Forget the roster and everything running. The owner stays registered."""
    global _started, _away
    _roster.clear()
    _started = False
    _away = False
    _tick_errors.clear()


# ── Lanes ────────────────────────────────────────────────────────────────────

def _add_lane(pSet, set_name: str) -> None:
    """A waypoint LANE_GU out from the region's home station along its world
    forward, facing away from it. Never "Player Start"."""
    anchor_name = _ANCHORS.get(set_name)
    if anchor_name is None or pSet.GetObject(LANE_NAME) is not None:
        return
    station = pSet.GetObject(anchor_name)
    if station is None:
        return
    import App
    loc = station.GetWorldLocation()
    rot = station.GetWorldRotation()
    fwd, up = rot.GetCol(1), rot.GetCol(2)
    wp = App.Waypoint_Create(LANE_NAME, set_name, None)
    if pSet.GetObject(LANE_NAME) is not wp:
        pSet.AddObjectToSet(wp, LANE_NAME)
    wp.SetStatic(1)
    wp.SetNavPoint(0)
    wp.SetTranslateXYZ(loc.x + LANE_GU * fwd.x, loc.y + LANE_GU * fwd.y,
                       loc.z + LANE_GU * fwd.z)
    wp.AlignToVectors(fwd, up)
    wp.Update(0)


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
            _roster.append(Shuttle(index=i, name="TC Shuttle %d" % i))
    for s in _roster:
        if s.phase is not Phase.DOCKED:
            _dock(s)
        s.timer = (s.index - 1) * _STAGGER_S
        s.bearing_accum = 0.0
        s.dock_name = None


# ── Docking in and out of the world ──────────────────────────────────────────

def _dock(shuttle: Shuttle) -> None:
    """Take the shuttle out of its set, drop its AI; it waits DOCK_S."""
    _release_bay(shuttle)
    ship = shuttle.ship
    if ship is not None:
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


def _bay_pose(station):
    """World (location, forward, up) of the station's "Docking Exit Start",
    the way DockWithStarbase.MakeWaypoints turns a bay point into a pose."""
    import MissionLib
    pos, fwd, up = MissionLib.GetPositionOrientationFromProperty(
        station, _BAY_EXIT)
    if None in (pos, fwd, up):
        raise AttributeError("%s has no position/orientation property (%s)"
                             % (station.GetName(), _BAY_EXIT))
    rot = station.GetWorldRotation()
    pos.MultMatrixLeft(rot)
    pos.Add(station.GetWorldLocation())
    fwd.MultMatrixLeft(rot)
    up.MultMatrixLeft(rot)
    return pos, fwd, up


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
    elif pSet.GetObject(shuttle.name) is not ship:
        pSet.AddObjectToSet(ship, shuttle.name)
    ship.SetTranslate(pos)
    ship.AlignToVectors(fwd, up)
    ship.UpdateNodeOnly()
    owners.tag(ship, OWNER_NAME, shuttle.index)
    shuttle.bearing_accum = 0.0
    _enter(shuttle, Phase.UNDOCKING)


class _ShuttleOwner:
    """Registered so a battle restore knows these ships are the service's, not
    battle objects; the service rebuilds them itself."""
    name = OWNER_NAME

    def rebuild(self, old, record):
        return None

    def after_rebuild(self, new, record) -> None:
        pass


owners.register(_ShuttleOwner())


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
    if back_gu:
        pos.SetXYZ(pos.x - back_gu * fwd.x, pos.y - back_gu * fwd.y,
                   pos.z - back_gu * fwd.z)
    wp.SetTranslate(pos)
    wp.AlignToVectors(fwd, up)
    wp.UpdateNodeOnly()


def _entry_points(station) -> None:
    """"Docking Entry" -> "Docking Entry End", built as MakeWaypoints builds
    them, and the approach point _CLEAR_GU outside the bay mouth."""
    pSet = station.GetContainingSet()
    start = _placement(pSet, _ENTRY, 5.0)
    end = _placement(pSet, _ENTRY_END, 2.0)
    nxt = start.GetNext()
    if nxt is None or nxt.GetObjID() != end.GetObjID():
        start.InsertAfterObj(end)
    _place_from_hardpoint(start, station, "Docking Entry Start")
    _place_from_hardpoint(end, station, "Docking Entry End")
    _place_from_hardpoint(_placement(pSet, _APPROACH_POINT, 4.0), station,
                          "Docking Entry Start", _CLEAR_GU)


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


def _give_ai(shuttle: Shuttle, ai) -> None:
    """Hand the ship this leg's AI (None: no AI) and remember the leg."""
    if ai is None:
        shuttle.ship.ClearAI()
    else:
        shuttle.ship.SetAI(ai)
    shuttle.ai = ai
    shuttle.leg = shuttle.phase


def _leg_done(shuttle: Shuttle) -> bool:
    """The leg's AI finished: the AI driver clears a finished tree."""
    return shuttle.ship.GetAI() is not shuttle.ai


def _plain(ship, name: str, module: str):
    import App
    ai = App.PlainAI_Create(ship, name)
    ai.SetScriptModule(module)
    ai.SetInterruptable(1)
    return ai


def _intercept(ship, target: str):
    ai = _plain(ship, "TCShuttleIntercept", "Intercept")
    script = ai.GetScriptInstance()
    script.SetTargetObjectName(target)
    script.SetInterceptDistance(_INTERCEPT_GU)
    script.SetInSystemWarpDistance(_IN_SYSTEM_WARP_GU)
    return ai


def _follow(ship, waypoint: str):
    ai = _plain(ship, "TCShuttleWaypoints", "FollowWaypoints")
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
    seq = App.SequenceAI_Create(s.ship, "TCShuttleUndock")
    seq.SetInterruptable(1)
    seq.SetLoopCount(1)
    seq.SetResetIfInterrupted(1)
    seq.SetDoubleCheckAllDone(0)
    seq.SetSkipDormant(0)
    seq.AddAI(undock_ai)
    seq.AddAI(_follow(s.ship, _EXIT_POINT))
    _hold_bay(s, station)
    _give_ai(s, seq)


def _start_departing(s: Shuttle) -> None:
    _give_ai(s, _intercept(s.ship, LANE_NAME))


def _start_warping_out(s: Shuttle) -> None:
    ai = _plain(s.ship, "TCShuttleWarp", "Warp")
    script = ai.GetScriptInstance()
    script.SetDestinationSetName("Systems.DryDock.DryDock")
    script.SetDestinationPlacementName(LANE_NAME)
    _give_ai(s, ai)


def _start_to_dock(s: Shuttle) -> None:
    # Placeholder until the Dry Docks legs exist: docks on the next tick.
    _give_ai(s, None)


def _start_approaching(s: Shuttle) -> None:
    station = _home_station()
    if station is None:
        _enter(s, Phase.WAITING)
        return
    _entry_points(station)
    _give_ai(s, _intercept(s.ship, _APPROACH_POINT))


def _start_entering(s: Shuttle) -> None:
    station = _home_station()
    if station is None:
        _enter(s, Phase.WAITING)
        return
    _entry_points(station)
    _hold_bay(s, station)
    _give_ai(s, _follow(s.ship, _ENTRY))


def _start_waiting(s: Shuttle) -> None:
    _release_bay(s)
    _give_ai(s, _intercept(s.ship, LANE_NAME))


_STARTS = {
    Phase.UNDOCKING: _start_undocking,
    Phase.DEPARTING: _start_departing,
    Phase.WARPING_OUT: _start_warping_out,
    Phase.TO_DOCK: _start_to_dock,
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


def _check_undocking(s: Shuttle) -> None:
    if _leg_done(s):
        _release_bay(s)
        _enter(s, Phase.DEPARTING)


def _check_departing(s: Shuttle) -> None:
    if _leg_done(s):
        _enter(s, Phase.WARPING_OUT)


def _check_warping_out(s: Shuttle) -> None:
    from engine.appc import warp_state
    pSet = s.ship.GetContainingSet()
    if (pSet is not None and pSet.GetName() == FAR_SET
            and not warp_state.is_ship_warping(s.ship)
            and not warp_state.is_arriving(s.ship)):
        _enter(s, Phase.TO_DOCK)


def _check_to_dock(s: Shuttle) -> None:
    _dock(s)


def _check_approaching(s: Shuttle) -> None:
    if _home_station() is None:
        _enter(s, Phase.WAITING)
    elif _leg_done(s):
        _enter(s, Phase.ENTERING)


def _check_entering(s: Shuttle) -> None:
    if _home_station() is None:
        _enter(s, Phase.WAITING)
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
        _give_ai(s, _plain(s.ship, "TCShuttleWait", "Stay"))


_CHECKS = {
    Phase.UNDOCKING: _check_undocking,
    Phase.DEPARTING: _check_departing,
    Phase.WARPING_OUT: _check_warping_out,
    Phase.TO_DOCK: _check_to_dock,
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


def _step(s: Shuttle, dt: float) -> None:
    if s.phase is Phase.DOCKED:
        s.timer -= dt
        if s.timer <= 0.0:
            _launch(s)
        return
    check = _CHECKS.get(s.phase)
    if check is None:
        return
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

    Pause rule: only a player in a system other than Tau Ceti pauses the
    service; no live player, or the warp transit set, leaves it as it is."""
    global _away
    try:
        if not _started:
            _start_if_ready()
            if not _started:
                return
        present = _player_presence()
        if present is None:
            return
        if not present:
            if not _away:
                _away = True
                for s in _roster:
                    if s.phase is not Phase.DOCKED:
                        _dock(s)
            return
        if _away:
            _away = False
            _restart()
    except Exception as exc:  # noqa: BLE001 - the loop must keep running
        msg = f"[shuttles] tick failed: {type(exc).__name__}: {exc}"
        if msg not in _tick_errors:   # a persistent failure prints once
            _tick_errors.add(msg)
            print(msg, flush=True)
        return
    for s in _roster:
        try:
            _step(s, dt)
        except Exception as exc:  # noqa: BLE001 - one shuttle must not stop the rest
            _park(s, exc)
