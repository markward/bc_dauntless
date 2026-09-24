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
_META_NEBULA_CALL = re.compile(r'App\.MetaNebula_Create\((.*?)\)', re.DOTALL)
_ADD_NEBULA_SPHERE = re.compile(r'AddNebulaSphere\((.*?)\)', re.DOTALL)


@dataclass
class SurveyedBody:
    name: str
    radius_gu: float
    model: str
    offset_gu: tuple
    is_sun: bool
    # Sun_Create's 4th argument (the texture that gives the star its colour).
    # Empty when BC passed fewer than four args -- that is BC's own default,
    # not a parse failure. Always "" for a planet.
    base_texture: str = ""


@dataclass
class SurveyedRegion:
    set_name: str
    ordinal: int | None
    bodies: list = field(default_factory=list)
    content_extent_gu: float = 0.0
    player_start_gu: tuple = (0.0, 0.0, 0.0)
    # {"color": (r, g, b), "spheres": [(x, y, z, radius_gu), ...],
    #  "visibility_gu": float, "sensor_density": float,
    #  "damage_hull_per_s": float, "damage_shield_per_s": float | None,
    #  "extra_nebulae": int} when this region's static file builds a
    # MetaNebula, else None. Colours are BC's own 0-1 floats; sphere
    # positions are set-local GU, read verbatim. damage_shield_per_s is
    # None when BC called SetupDamage with a single argument (shield rate
    # unauthored, not zero). extra_nebulae counts MetaNebula_Create calls
    # beyond the first -- only Multi5 (not a region) has any.
    nebula: dict | None = None
    # Unit forward of the BRIGHTEST directional light this region authors --
    # "where the light shines", so it points FROM the star TOWARD the region.
    # The layout places the region along it, which is what makes BC's own
    # lighting agree with where we put the star. None when a region authors no
    # directional at all. Fills are ignored: only the key light says where the
    # artists thought the star was.
    key_light_dir: tuple | None = None
    # True when the system's CreateSystemMenu names this set -- i.e. it is a
    # place BC actually lets the player go. False for orphans still in the
    # tree: Vesuvi1 is the only one across all 32 systems.
    menu_listed: bool = True


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


def _split_top_level(s: str) -> list:
    """Split on commas that are not inside a quoted string.

    BC writes plain comma-separated argument lists with no nested parens, but
    a quoted texture path could in principle contain a comma -- respecting
    quotes here is cheap insurance, not a case that has actually been seen.
    """
    parts, cur, in_str = [], [], False
    for ch in s:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif ch == ',' and not in_str:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append(''.join(cur))
    return [p.strip() for p in parts]


def _eval_num(expr: str) -> float:
    """BC writes nebula colours as expressions ('100.0 / 255.0'), not
    literals -- evaluate numerically rather than pattern-matching the text.
    No builtins/names are exposed, so this only ever evaluates arithmetic on
    literal numbers."""
    return float(eval(expr, {"__builtins__": {}}, {}))


_SETUP_DAMAGE = re.compile(r'SetupDamage\((.*?)\)', re.DOTALL)


def _nebula(text: str):
    """This region's MetaNebula, if its static file builds one.

    BC's own parameter order, from the comment block the artists left in
    Vesuvi4_S.py: r, g, b, visibility distance, sensor density, internal
    texture, external texture. Damage is separate, via SetupDamage.

    A file may build SEVERAL MetaNebulae -- Multi5 builds four. Each owns only
    the AddNebulaSphere and SetupDamage calls that follow it, so the text is
    sliced at the create calls before anything is collected. Collecting across
    the whole file instead gave the first nebula every sphere in the set.
    Only the first is returned; `extra_nebulae` counts the rest so the caller
    can report them rather than silently drop them.
    """
    joined = "\n".join(_uncommented(text))
    creates = list(_META_NEBULA_CALL.finditer(joined))
    if not creates:
        return None

    first = creates[0]
    # Everything from the first create up to the next one (or end of file).
    end = creates[1].start() if len(creates) > 1 else len(joined)
    scope = joined[first.end():end]

    args = _split_top_level(first.group(1))
    color = tuple(_eval_num(a) for a in args[:3])
    visibility = _eval_num(args[3]) if len(args) > 3 else 0.0
    sensor_density = _eval_num(args[4]) if len(args) > 4 else 0.0

    hull, shield = 0.0, 0.0
    dm = _SETUP_DAMAGE.search(scope)
    if dm:
        parts = _split_top_level(dm.group(1))
        hull = _eval_num(parts[0]) if parts and parts[0] else 0.0
        # One argument means BC authored no shield rate. That is unknown, not
        # zero -- absent SetupDamage is the case that means zero.
        shield = _eval_num(parts[1]) if len(parts) > 1 else None

    spheres = []
    for sm in _ADD_NEBULA_SPHERE.finditer(scope):
        parts = _split_top_level(sm.group(1))
        if len(parts) != 4:
            continue
        spheres.append(tuple(_eval_num(p) for p in parts))

    return {
        "color": color,
        "spheres": spheres,
        "visibility_gu": visibility,
        "sensor_density": sensor_density,
        "damage_hull_per_s": hull,
        "damage_shield_per_s": shield,
        "extra_nebulae": len(creates) - 1,
    }


_DIR_LIGHT = re.compile(
    r'kForward\s*=\s*App\.TGPoint3\(\)\s*\n\s*kForward\.SetXYZ\(([^)]*)\)'
    r'[\s\S]{0,400}?ConfigDirectionalLight\(([^)]*)\)')
_MENU_CALL = re.compile(r'CreateSystemMenu\((.*?)\)', re.DOTALL)


def _key_light(text: str):
    """Unit forward of the brightest ConfigDirectionalLight in a region script.

    BC builds a light by aiming a LightPlacement (kForward / AlignToVectors)
    and then calling ConfigDirectionalLight(r, g, b, dimmer) on it, so the
    forward that belongs to a light is the one immediately preceding its
    Config call. A region may author several -- Vesuvi 5 has a key at 0.7 and
    a fill at 0.3 -- and only the brightest is evidence about the star.

    None when the region authors no directional at all.
    """
    best = None
    for m in _DIR_LIGHT.finditer("\n".join(_uncommented(text))):
        parts = _split_top_level(m.group(1))
        if len(parts) != 3:
            continue
        try:
            fwd = tuple(_eval_num(p) for p in parts)
            dimmer = _eval_num(_split_top_level(m.group(2))[3])
        except (ValueError, IndexError, SyntaxError, NameError, ZeroDivisionError):
            continue
        if best is None or dimmer > best[0]:
            best = (dimmer, fwd)
    if best is None:
        return None
    length = math.sqrt(sum(c * c for c in best[1]))
    if length <= 0.0:
        return None
    return tuple(c / length for c in best[1])


def _menu_sets(system: str) -> set:
    """The set names this system's CreateSystemMenu actually offers.

    The call is CreateSystemMenu(display_name, default, *places). A system with
    several places lists them after the default; a SINGLE-place system passes
    only the default and no list at all -- Riha is the one instance -- so
    reading the tail arguments alone would mark its only place unlisted.

    Empty when the head script cannot be read, which the caller must treat as
    "no opinion" rather than "nothing is listed".
    """
    head = _systems_dir() / system / f"{system}.py"
    if not head.is_file():
        return set()
    m = _MENU_CALL.search(_read(head))
    if not m:
        return set()
    args = [a.strip().strip('"').strip("'") for a in m.group(1).split(",")]
    if len(args) < 2:
        return set()
    tail = {a.split(".")[-1] for a in args[2:] if a}
    return tail or {args[1].split(".")[-1]}


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
        base_texture = ""
        if kind == "Sun":
            arg_parts = _split_top_level(args)
            if len(arg_parts) >= 4:
                tex_match = re.search(r'"([^"]*)"', arg_parts[3])
                if tex_match:
                    base_texture = tex_match.group(1)
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
                                   offset_gu=offset, is_sun=(kind == "Sun"),
                                   base_texture=base_texture))
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
    listed = _menu_sets(system)
    for path in sorted(d.glob("*.py")):
        stem = path.stem
        if stem in ("__init__", system) or stem.endswith("_S"):
            continue
        text = _read(path)
        placements = _placements(text)
        static = d / f"{stem}_S.py"
        bodies, used = ([], set())
        nebula = None
        if static.is_file():
            static_text = _read(static)
            bodies, used = _bodies(static_text, placements)
            nebula = _nebula(static_text)
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
            nebula=nebula,
            key_light_dir=_key_light(text),
            # An unreadable or menu-less head script yields an empty set, which
            # must not silently unlist every region in the system.
            menu_listed=(stem in listed) if listed else True,
        ))
    result.regions.sort(key=lambda r: (r.ordinal is None, r.ordinal or 0, r.set_name))
    return result


def survey_all() -> list:
    return [survey_system(n) for n in system_names()]


def bc_radii(surveyed) -> dict:
    """{(region_set_name, body_name): BC radius in GU} for every non-sun body.

    The input the validator's radius-ratio rule compares the map against.
    Suns are excluded: the star is scaled by sun_radius_scale, not the body
    scale, and systems with no Sun_Create get a generated brown dwarf.
    """
    return {(r.set_name, b.name): b.radius_gu
            for r in surveyed.regions for b in r.bodies if not b.is_sun}
