"""Read BC's Systems/ tree and report what each region actually contains.

Reads Python 1.5 source as TEXT and never imports it. The SDK's placement
files are flat generated code -- a `*_Create("Name", sSetName, ...)` line
followed by a `SetTranslateXYZ(...)` line -- so a line scanner is sufficient
and correct. (tools/probes/ aside, modern `ast` cannot parse 1.5 sources
anyway.)

Two things this deliberately does NOT do:

* It never looks a body up by waypoint name. The design doc records four
  spellings for "the planet" (`Planet Location` x52, `Planet` x20, `Planet1`
  x13, `Planet Placement`) plus `Colony` and two named after the set itself,
  and six for moons. The only reliable route is Planet_Create -> the variable
  -> its AddObjectToSet display name and PlaceObjectByName waypoint.
* It never decides layout. Where a body ENDS UP is tools/systems/layout.py's
  job; this module only reports where BC put it.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine import paths

_CREATE_PLACEMENT = re.compile(r'App\.(\w+)_Create\("([^"]+)",\s*("([^"]+)"|\w+)')
_TRANSLATE = re.compile(r'SetTranslateXYZ\(([^)]*)\)')
_BODY_CREATE = re.compile(r'(\w+)\s*=\s*App\.(Planet|Sun)_Create\((.*)\)\s*$')
_LOAD_PLACEMENTS_DEFAULT = re.compile(r'def LoadPlacements\(\s*sSetName\s*=\s*"([^"]+)"')
_TRAILING_INT = re.compile(r'(\d+)$')


@dataclass
class SurveyedBody:
    name: str
    radius_gu: float
    model: str
    offset_gu: tuple
    is_sun: bool


@dataclass
class SurveyedRegion:
    set_name: str
    ordinal: int | None
    bodies: list = field(default_factory=list)
    content_extent_gu: float = 0.0
    player_start_gu: tuple = (0.0, 0.0, 0.0)


@dataclass
class SurveyedSystem:
    name: str
    regions: list = field(default_factory=list)
    pins: dict = field(default_factory=dict)


def _systems_dir() -> Path:
    return paths.sdk_scripts() / "Systems"


def _missions_dir() -> Path:
    return paths.sdk_scripts() / "Maelstrom"


def _read(path: Path) -> str:
    return path.read_text(encoding="latin-1")


def _uncommented(text: str):
    for line in text.splitlines():
        if not line.lstrip().startswith("#"):
            yield line


def _xyz(raw: str):
    try:
        parts = [float(v) for v in raw.split(",")]
    except ValueError:
        return None
    return tuple(parts) if len(parts) == 3 else None


def _placements(text: str) -> dict:
    """name -> xyz for every placement created in this file."""
    out, pending = {}, None
    for line in _uncommented(text):
        m = _CREATE_PLACEMENT.search(line)
        if m:
            pending = m.group(2)
            continue
        m = _TRANSLATE.search(line)
        if m and pending is not None:
            xyz = _xyz(m.group(1))
            if xyz is not None:
                out[pending] = xyz
            pending = None
    return out


def _bodies(static_text: str, placements: dict) -> tuple:
    """(bodies, waypoint names consumed by bodies)."""
    bodies, used = [], set()
    lines = list(_uncommented(static_text))
    for i, line in enumerate(lines):
        m = _BODY_CREATE.search(line)
        if not m:
            continue
        var, kind, args = m.group(1), m.group(2), m.group(3)
        try:
            radius = float(args.split(",")[0])
        except ValueError:
            radius = 0.0
        model = ""
        model_match = re.search(r'"([^"]*\.nif)"', args)
        if model_match:
            model = model_match.group(1)
        display, waypoint = None, None
        for later in lines[i + 1:]:
            if display is None:
                m2 = re.search(r'AddObjectToSet\(\s*%s\s*,\s*"([^"]+)"' % re.escape(var), later)
                if m2:
                    display = m2.group(1)
            if waypoint is None:
                m2 = re.search(r'%s\.PlaceObjectByName\(\s*"([^"]+)"' % re.escape(var), later)
                if m2:
                    waypoint = m2.group(1)
            if display is not None and waypoint is not None:
                break
        if display is None:
            continue
        offset = placements.get(waypoint, (0.0, 0.0, 0.0)) if waypoint else (0.0, 0.0, 0.0)
        if waypoint:
            used.add(waypoint)
        bodies.append(SurveyedBody(name=display, radius_gu=radius, model=model,
                                   offset_gu=offset, is_sun=(kind == "Sun")))
    return bodies, used


def _mission_extent(set_name: str) -> float:
    """Largest distance from the origin of any placement a mission puts in this set."""
    best = 0.0
    root = _missions_dir()
    if not root.is_dir():
        return best
    for path in root.rglob("*.py"):
        text = _read(path)
        # A module is "about" this set if it names it literally, or if its own
        # filename does and its placements take sSetName.
        filename_hint = ("_%s_" % set_name) in path.name or path.stem == f"{set_name}_P"
        if set_name not in text and not filename_hint:
            continue
        default = None
        m = _LOAD_PLACEMENTS_DEFAULT.search(text)
        if m:
            default = m.group(1)
        pending = None
        for line in _uncommented(text):
            m = _CREATE_PLACEMENT.search(line)
            if m:
                literal = m.group(4)
                target = literal if literal else (default or (set_name if filename_hint else None))
                pending = target
                continue
            m = _TRANSLATE.search(line)
            if m and pending is not None:
                if pending == set_name:
                    xyz = _xyz(m.group(1))
                    if xyz is not None:
                        best = max(best, math.sqrt(sum(c * c for c in xyz)))
                pending = None
    return best


def system_names() -> list:
    out = []
    root = _systems_dir()
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        head = d / f"{d.name}.py"
        if head.is_file() and "CreateSystemMenu" in _read(head):
            out.append(d.name)
    return sorted(out)


def survey_system(system: str) -> SurveyedSystem:
    d = _systems_dir() / system
    result = SurveyedSystem(name=system)
    for path in sorted(d.glob("*.py")):
        stem = path.stem
        if stem in ("__init__", system) or stem.endswith("_S"):
            continue
        text = _read(path)
        placements = _placements(text)
        static = d / f"{stem}_S.py"
        bodies, used = ([], set())
        if static.is_file():
            bodies, used = _bodies(_read(static), placements)
        skip = used | {"Sun"}
        extent = 0.0
        for name, xyz in placements.items():
            if name in skip:
                continue
            extent = max(extent, math.sqrt(sum(c * c for c in xyz)))
        extent = max(extent, _mission_extent(stem))
        ordinal_match = _TRAILING_INT.search(stem)
        result.regions.append(SurveyedRegion(
            set_name=stem,
            ordinal=int(ordinal_match.group(1)) if ordinal_match else None,
            bodies=bodies,
            content_extent_gu=extent,
            player_start_gu=placements.get("Player Start", (0.0, 0.0, 0.0)),
        ))
    result.regions.sort(key=lambda r: (r.ordinal is None, r.ordinal or 0, r.set_name))
    return result


def survey_all() -> list:
    return [survey_system(n) for n in system_names()]
