"""The home-station table and a reader for one SDK placement point.

`home_stations.json` lists the stations BC's Maelstrom missions create, by
(set, name), with the ship script and the SDK placement point each one sits at.
No coordinate is stored: `read_point` takes the point out of the SDK's own
placement file at run time.

The path is computed inside `table()`, never held at import.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from engine.appc import ship_lifecycle
from engine.appc.math import TGMatrix3, TGPoint3
from engine.systems import owners

_FORMAT = 1
_KEYS = ("set", "name", "script", "point", "point_module")
_PROBE_SET = "__dauntless_home_station_probe__"

_table_cache = None


@dataclass(frozen=True)
class Station:
    set_name: str
    name: str
    script: str
    point: str
    point_module: str


def load_table(path) -> tuple:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"home stations: cannot read {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("home stations: top level must be an object")
    if doc.get("format") != _FORMAT:
        raise ValueError(
            f"home stations: unsupported format {doc.get('format')!r}")
    extra = sorted(set(doc) - {"format", "stations"})
    if extra:
        raise ValueError(f"home stations: unknown key(s) {extra}")
    rows = doc.get("stations")
    if not isinstance(rows, list):
        raise ValueError("home stations: 'stations' must be a list")
    out = []
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"home stations: row {i} must be an object")
        extra = sorted(set(row) - set(_KEYS))
        if extra:
            raise ValueError(f"home stations: row {i} unknown key(s) {extra}")
        for key in _KEYS:
            if key not in row:
                raise ValueError(f"home stations: row {i} missing key '{key}'")
            if not isinstance(row[key], str) or not row[key]:
                raise ValueError(
                    f"home stations: row {i} '{key}' must be a non-empty string")
        ident = (row["set"], row["name"])
        if ident in seen:
            raise ValueError(f"home stations: duplicate station {ident}")
        seen.add(ident)
        out.append(Station(row["set"], row["name"], row["script"],
                           row["point"], row["point_module"]))
    return tuple(out)


def table() -> tuple:
    global _table_cache
    if _table_cache is None:
        _table_cache = load_table(Path(__file__).with_name("home_stations.json"))
    return _table_cache


def stations_for_set(set_name: str) -> tuple:
    return tuple(s for s in table() if s.set_name == set_name)


def _copy_pose(wp):
    loc = wp.GetWorldLocation()
    rot = wp.GetWorldRotation()
    m = TGMatrix3()
    m.set_from_tuple(rot.as_tuple())
    return TGPoint3(loc.x, loc.y, loc.z), m


def read_point(station: Station, pSet):
    """Copies of the point's world location and rotation, or None."""
    if station.point_module == pSet.GetRegionModule():
        wp = pSet.GetObject(station.point)
        return None if wp is None else _copy_pose(wp)

    from engine.appc import placement
    module = importlib.import_module(station.point_module)
    saved = dict(placement._waypoint_registry)
    try:
        module.LoadPlacements(_PROBE_SET)
        wp = placement._waypoint_registry.get(station.point)
        return None if wp is None else _copy_pose(wp)
    finally:
        placement._waypoint_registry.clear()
        placement._waypoint_registry.update(saved)


# ── Placement, the owner, and "is this station still standing?" ──────────────

OWNER_NAME = "home_stations"

# (set_name, name) of every home station destroyed since the last reset().
_destroyed: set = set()


def is_standing(station: Station) -> bool:
    """The only gate on placing a station: False once it was destroyed since
    the current mission started (reset() runs on every mission change)."""
    return (station.set_name, station.name) not in _destroyed


def forget_destroyed(station: Station) -> None:
    _destroyed.discard((station.set_name, station.name))


def reset() -> None:
    """Clear the destroyed record. The owner stays registered."""
    _destroyed.clear()


def mark_home(obj, station: Station) -> None:
    owners.tag(obj, OWNER_NAME, station)


def home_station_of(obj):
    """The table row `obj` was placed for, or None."""
    owned = owners.owner_of(obj)
    if owned is None or owned[0].name != OWNER_NAME:
        return None
    return owned[1]


def _build(row: Station, pSet, loc, rot):
    """Create one station with BC's own CreateShip and set it on its point.

    No placement name and bGrabPreloaded=0: a station never takes a mission's
    precreated ship. Shared by place_for_set and the owner's rebuild, so a
    region build and a battle rebuild make the same object.

    BC's CreateShip, never the reuse wrapper: a battle rebuild runs while the
    old (scarred) station may still hold the name, and the wrapper would
    hand that one back."""
    import loadspacehelper
    create = getattr(loadspacehelper.CreateShip,
                     "_dauntless_home_station_orig", loadspacehelper.CreateShip)
    obj = create(row.script, pSet, row.name, "", 0, 0)
    obj.SetTranslate(loc)
    obj.SetMatrixRotation(rot)
    obj.UpdateNodeOnly()
    mark_home(obj, row)
    return obj


def place_for_set(pSet, set_name: str) -> list:
    """Place every standing home station of `set_name` that the set does not
    already hold. One bad row prints one line and never stops the others."""
    placed = []
    for row in stations_for_set(set_name):
        try:
            if not is_standing(row):
                continue
            if pSet.GetObject(row.name) is not None:
                continue
            pose = read_point(row, pSet)
            if pose is None:
                continue
            placed.append(_build(row, pSet, *pose))
        except Exception as exc:  # noqa: BLE001 - one row must not stop the rest
            print(f"[home-stations] {set_name}/{row.name} not placed: "
                  f"{type(exc).__name__}: {exc}", flush=True)
    return placed


# ── A mission's own CreateShip for a placed station ──────────────────────────

def reusable(pcScript: str, pSet, name: str):
    """The placed home station a mission's CreateShip(pcScript, pSet, name)
    asks for, or None: `pSet` holds an object named `name` that home_stations
    placed, built from the same ship script, and not dying or dead."""
    if pSet is None:
        return None
    obj = pSet.GetObject(name)
    if obj is None or home_station_of(obj) is None:
        return None
    if obj.GetScript() != "ships." + pcScript:
        return None
    from engine.appc import ship_death
    if ship_death._out_of_action(obj):
        return None
    return obj


def install_create_ship_hook(module) -> bool:
    """Wrap `module.CreateShip` (SDK loadspacehelper) so a mission's call for a
    placed home station returns that station, moved to the mission's point,
    instead of building a second one. BC's AddObjectToSet refuses a duplicate
    name; ours overwrites it, which would orphan the region's station.

    Anything else, including _build's own call (place_for_set skips a name the
    set already holds, so reusable finds nothing), goes to BC's CreateShip.
    Idempotent: True only when it installs the wrapper."""
    orig = module.__dict__.get("CreateShip")
    if orig is None or "_dauntless_home_station_orig" in getattr(
            orig, "__dict__", {}):
        return False

    def CreateShip(pcScript, pSet, pcIdentifier, pcLocationName,
                   iWarpFlash=0, bGrabPreloaded=1):
        station = reusable(pcScript, pSet, pcIdentifier)
        if station is None:
            return orig(pcScript, pSet, pcIdentifier, pcLocationName,
                        iWarpFlash, bGrabPreloaded)
        # The station is already in place: no warp flash for it.
        if pcLocationName:
            station.PlaceObjectByName(pcLocationName)
        station.UpdateNodeOnly()
        return station

    CreateShip._dauntless_home_station_orig = orig
    module.CreateShip = CreateShip
    return True


class _HomeStationsOwner:
    name = OWNER_NAME

    def rebuild(self, old, record):
        return _build(record.key, record.pset, record.location, record.rotation)

    def after_rebuild(self, new, record) -> None:
        forget_destroyed(record.key)


def _on_lifecycle(event: str, ship) -> None:
    """Record a home station's destruction while it is still in a set."""
    if event != "destroyed":
        return
    station = home_station_of(ship)
    if station is None or ship.GetContainingSet() is None:
        return
    _destroyed.add((station.set_name, station.name))


owners.register(_HomeStationsOwner())
ship_lifecycle.subscribe(_on_lifecycle)
