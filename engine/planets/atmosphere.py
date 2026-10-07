"""Planet atmosphere catalogue (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §3).

Keys are a NIF stem (case-folded basename, no extension) -- the default for
every planet using that NIF -- or "<set>/<name>", BC's own identity for one
planet (AddSet name + AddObjectToSet name), which wins. A bare object name is
not a key: "Moon 1" exists in three sets. The JSON lives under the project
asset root and is resolved at USE, never at import.
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass

_memo: dict = {}      # str(path) -> dict of raw entries
_warned: set = set()  # (str(path), key) already reported

# In-memory overlay set by the "atmosphere" dev dial group (Task 7):
# key -> Atmosphere, consulted by resolve() before the catalogue file.
# Cleared by reload() along with the file memo, so a reload (the dev
# "reload action", or the test suite's autouse reset) drops live tuning too.
_overrides: dict = {}

# Live registry of every planet instance the current session has pushed an
# atmosphere decision for while the toggle was on -- airless (None) ones
# INCLUDED, so a catalogue reload can re-push them (atmosphere_dials.
# repush_live); the dial target (host_loop._nearest_live_planet) skips them.
# Cleared on mission/set teardown and by the test suite's autouse reset.
_live: list = []


@dataclass(frozen=True)
class LivePlanet:
    iid: object
    key: str | None
    set_name: str
    obj_name: str
    nif_path: str
    # "set": a Planet object realized from its set (realize_set_objects /
    # mission load). "celestial": a system-map body drawn by
    # host_loop._reconcile_celestial_instances, whose set_name is its REGION
    # and whose lifetime follows the draw list, not that set.
    source: str = "set"


def record_live(iid, key, set_name: str, obj_name: str, nif_path: str,
                source: str = "set") -> None:
    _live.append(LivePlanet(iid=iid, key=key, set_name=set_name,
                            obj_name=obj_name, nif_path=nif_path, source=source))


def iid_eq(a, b) -> bool:
    """InstanceId equality: pybind's InstanceId has no __eq__, only readonly
    `index`/`generation`, so plain `==` is identity there and would never
    match two Python wrappers of the same engine instance. Plain values
    (tests use strings) fall through to `==`."""
    ai, bi = getattr(a, "index", None), getattr(b, "index", None)
    if ai is not None and bi is not None:
        return ai == bi and getattr(a, "generation", None) == getattr(b, "generation", None)
    return a == b


def forget_live(iid) -> None:
    """Drop the live entry for a destroyed instance (any source)."""
    _live[:] = [lp for lp in _live if not iid_eq(lp.iid, iid)]


def live() -> tuple:
    return tuple(_live)


def clear_live() -> None:
    _live.clear()


def clear_live_for_set(set_name: str) -> None:
    """Drop only this set's live entries. teardown_set_objects tears down a
    SINGLE set's render instances mid-mission (e.g. the warp spine's source
    set, after the destination set has already been realized) -- a blanket
    clear_live() there would wipe the destination's just-recorded planets
    too. MissionSession.teardown (whole-session end) still uses the blanket
    clear_live(). Only SET-realized entries go: a celestial map body records
    its region as set_name, but the celestial pass keeps drawing it after the
    region's set is torn down (it forgets its own via forget_live)."""
    _live[:] = [lp for lp in _live
                if not (lp.source == "set" and lp.set_name == set_name)]

_FIELDS = {"color", "sunset_color", "thickness", "density", "limb", "atmosphere",
           "intensity", "mie"}

STOCK_STEMS: tuple = (
    "pinkgasplanet", "bluewhitegasplanet", "tangasplanet", "gasgiant",
    "greenpurpleplanet", "purpleplanet", "purplewhiteplanet", "aquaplanet", "planet",
    "brownblueplanet", "snowplanet", "greenplanet", "slimegreenplanet",
    "bluegrayplanet", "bluetanplanet", "turquoiseplanet", "brightgreenplanet",
    "earth", "lavenderplanet",
    "bluerockyplanet", "brownplanet", "dryplanet", "iceplanet", "redplanet",
    "sulfurplanet", "rootbeerplanet", "redswirlplanet",
    "moon", "rockyplanet", "grayplanet", "tanplanet",
)


@dataclass(frozen=True)
class Atmosphere:
    # Linear RGB RELATIVE per-channel Rayleigh scattering strength, not a
    # final tint: the shader normalises it by its strongest channel, so the
    # hue emerges from scattering (blue sky, reddened long paths).
    color: tuple
    sunset_color: tuple
    thickness: float
    density: float
    limb: float
    # Shell-halo brightness multiplier only (NOT the opaque.frag surface limb
    # term, which has its own `limb` knob). The shader's in-scatter peaks at
    # ~0.06 at the lit limb against a sun colour of ~1, far under the lit
    # surface -- this covers the gap. Last field so existing positional
    # 5-arg construction stays compatible.
    intensity: float = 20.0
    # Grey Mie forward-lobe strength (extinction sigma * mie in every
    # channel, HG g = 0.76). After `intensity` so positional 5- and 6-arg
    # construction stays compatible.
    mie: float = 0.2


def nif_stem(nif_path: str) -> str:
    return pathlib.PurePath(nif_path.replace("\\", "/")).stem.casefold()


def srgb_hex_to_linear(hex_str: str) -> tuple:
    if not (isinstance(hex_str, str) and len(hex_str) == 7 and hex_str[0] == "#"):
        raise ValueError(f"colour must be '#RRGGBB', got {hex_str!r}")
    out = []
    for i in (1, 3, 5):
        c = int(hex_str[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def catalogue_path() -> pathlib.Path:
    from engine import paths
    return pathlib.Path(paths.project_asset_root()) / "planets" / "atmospheres.json"


def _warn(path_key: str, key: str, msg: str) -> None:
    if (path_key, key) not in _warned:
        _warned.add((path_key, key))
        print(f"[atmosphere] {key}: {msg}", file=sys.stderr)


def load() -> dict:
    path = catalogue_path()
    key = str(path)
    if key in _memo:
        return _memo[key]
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("top level must be an object")
    except (OSError, ValueError) as e:
        if isinstance(e, OSError):
            msg = f"unreadable ({e.strerror}); every planet is airless"
        else:
            msg = f"unreadable ({e}); every planet is airless"
        _warn(key, "atmospheres.json", msg)
        raw = {}
    _memo[key] = raw
    return raw


def reload() -> None:
    _memo.clear()
    _warned.clear()
    _overrides.clear()


def set_override(key: str, a: Atmosphere) -> None:
    """Overlay `key`'s resolved Atmosphere with `a` (the atmosphere dev dial
    group, Task 7). Takes effect for every planet that resolves to `key`,
    not only the one the dial targeted -- the dial edits the CATALOGUE
    entry, not one instance."""
    _overrides[key] = a


def _num(entry: dict, name: str, lo: float, hi: float, lo_open: bool = False) -> float:
    v = entry[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} must be a number")
    v = float(v)
    if (v <= lo if lo_open else v < lo) or v > hi:
        raise ValueError(f"{name}={v} out of range")
    return v


def parse_entry(key: str, entry: dict):
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    unknown = set(entry) - _FIELDS
    if unknown:
        raise ValueError(f"unknown field(s) {sorted(unknown)}")
    if entry.get("atmosphere") is False:
        return None
    required = {"color", "thickness", "density", "limb"}
    missing = required - set(entry.keys())
    if missing:
        raise ValueError(f"missing required field(s) {sorted(missing)}")
    color = srgb_hex_to_linear(entry["color"])
    sunset = srgb_hex_to_linear(entry["sunset_color"]) if "sunset_color" in entry else color
    intensity = _num(entry, "intensity", 0.0, 50.0) if "intensity" in entry else 20.0
    mie = _num(entry, "mie", 0.0, 4.0) if "mie" in entry else 0.2
    return Atmosphere(
        color=color, sunset_color=sunset,
        thickness=_num(entry, "thickness", 0.0, 0.25, lo_open=True),
        density=_num(entry, "density", 0.0, 4.0),
        limb=_num(entry, "limb", 0.0, 4.0),
        intensity=intensity,
        mie=mie,
    )


def resolve_key(set_name: str, obj_name: str, nif_path: str):
    raw = load()
    override = f"{set_name}/{obj_name}"
    if set_name and override in raw:
        return override
    stem = nif_stem(nif_path)
    return stem if stem in raw else None


def resolve(set_name: str, obj_name: str, nif_path: str):
    key = resolve_key(set_name, obj_name, nif_path)
    if key is None:
        return None
    if key in _overrides:
        return _overrides[key]
    try:
        return parse_entry(key, load()[key])
    except (ValueError, KeyError, TypeError) as e:
        _warn(str(catalogue_path()), key, f"malformed ({e}); treated as airless")
        return None
