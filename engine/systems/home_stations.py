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

from engine.appc.math import TGMatrix3, TGPoint3

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
