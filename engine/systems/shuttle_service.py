"""The Tau Ceti shuttle service: ten Federation shuttles between Starbase 12
and the Dry Docks.

A shuttle is a record, not a world object, while it is docked: it is in no set
and costs nothing. `_launch` puts it into the Starbase 12 set at the bay's
"Docking Exit Start"; `_dock` takes it out again. The service runs in every
game mode, belongs to no mission group, and pauses (every shuttle docked,
timers frozen) while the player is in another system. Away rule: only a player
in a system other than Tau Ceti pauses it; no live player, or the player in the
warp transit set, leaves it exactly as it is.

This is the first task of the service: the roster, the lane waypoints, the
staggered start and docking out of the world. Phases after UNDOCKING are
defined but not driven yet.
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


_roster: list = []
_started = False
_away = False
_rng = random.Random()


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
    """Create (first time) or re-add the shuttle at Starbase 12's exit point."""
    import App
    pSet = App.g_kSetManager.GetSet(HOME_SET)
    station = None if pSet is None else pSet.GetObject(_ANCHORS[HOME_SET])
    if station is None:
        return
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
    shuttle.phase = Phase.UNDOCKING
    shuttle.bearing_accum = 0.0


class _ShuttleOwner:
    """Registered so a battle restore knows these ships are the service's, not
    battle objects; the service rebuilds them itself."""
    name = OWNER_NAME

    def rebuild(self, old, record):
        return None

    def after_rebuild(self, new, record) -> None:
        pass


owners.register(_ShuttleOwner())


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
    if s.phase is Phase.UNDOCKING:
        # Placeholder until the flying legs exist: a launched shuttle must not
        # sit motionless on the bay pose, so it docks again on the next tick.
        _dock(s)
    elif s.phase is Phase.DOCKED:
        s.timer -= dt
        if s.timer <= 0.0:
            _launch(s)


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
        print(f"[shuttles] tick failed: {type(exc).__name__}: {exc}", flush=True)
        return
    for s in _roster:
        try:
            _step(s, dt)
        except Exception as exc:  # noqa: BLE001 - one shuttle must not stop the rest
            _park(s, exc)
