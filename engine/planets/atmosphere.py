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

_FIELDS = {"color", "sunset_color", "thickness", "density", "limb", "atmosphere"}

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
    color: tuple
    sunset_color: tuple
    thickness: float
    density: float
    limb: float


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
    return Atmosphere(
        color=color, sunset_color=sunset,
        thickness=_num(entry, "thickness", 0.0, 0.25, lo_open=True),
        density=_num(entry, "density", 0.0, 4.0),
        limb=_num(entry, "limb", 0.0, 4.0),
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
    try:
        return parse_entry(key, load()[key])
    except (ValueError, KeyError, TypeError) as e:
        _warn(str(catalogue_path()), key, f"malformed ({e}); treated as airless")
        return None
