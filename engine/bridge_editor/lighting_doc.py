"""Per-bridge lighting document (spec 2026-10-08-bridge-emitters §7).

One JSON file per bridge NIF, keyed by the NIF's content hash, holding
per-shape `material` and `emitter` sections plus shared `profiles`. Only
references and parameters -- never BC geometry. Unknown keys are REJECTED:
a typo must fail loudly, not be silently ignored."""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine import paths

FORMAT = 1
MOD_REL = "dauntless/bridge_lighting"

_STATES = ("green", "yellow", "red")


class BridgeLightingError(ValueError):
    pass


def project_dir() -> Path:
    return paths.project_asset_root() / "bridge_lighting"


def candidate_paths(content_hash) -> list:
    """Mod and replacement dirs first, then the project. The stock install
    (game_asset_dirs' LAST entry) is never searched -- it holds no such data."""
    mod_dirs = paths.game_asset_dirs(MOD_REL)[:-1]
    return ([Path(d) / f"{content_hash}.json" for d in mod_dirs]
            + [project_dir() / f"{content_hash}.json"])


def find(content_hash) -> Optional[Path]:
    for p in candidate_paths(content_hash):
        if p.is_file():
            return p
    return None


def empty_doc(source) -> dict:
    return {"format": FORMAT, "source": str(source), "profiles": {}, "shapes": {}}


def shape_entry(doc, block, name) -> dict:
    key = f"{block}:{name}"
    entry = doc["shapes"].get(key)
    if entry is None:
        entry = {"block": int(block), "name": str(name)}
        doc["shapes"][key] = entry
    return entry


# ── validation ──────────────────────────────────────────────────────────────

def _fail(where, msg):
    raise BridgeLightingError(f"{where}: {msg}")


def _obj(v, where, allowed, required=()):
    if not isinstance(v, dict):
        _fail(where, "must be an object")
    for k in v:
        if k not in allowed:
            _fail(f"{where}.{k}", "unknown key")
    for k in required:
        if k not in v:
            _fail(f"{where}.{k}", "required")


def _num(v, where, lo=None, hi=None, lo_open=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _fail(where, "must be a finite number")
    if lo is not None and (v <= lo if lo_open else v < lo):
        _fail(where, f"must be {'>' if lo_open else '>='} {lo}")
    if hi is not None and v > hi:
        _fail(where, f"must be <= {hi}")


def _vec3(v, where, lo=None):
    if not isinstance(v, list) or len(v) != 3:
        _fail(where, "must be a list of 3 numbers")
    for i, c in enumerate(v):
        _num(c, f"{where}[{i}]", lo=lo)


def _enum(v, where, options):
    if v not in options:
        _fail(where, f"must be one of {', '.join(options)}")


def _wave(w, where):
    _obj(w, where, {"shape", "period_s", "duty", "soft", "min"}, ("shape",))
    _enum(w["shape"], f"{where}.shape", ("steady", "sine", "square"))
    if w["shape"] != "steady":
        if "period_s" not in w:
            _fail(f"{where}.period_s", "required unless steady")
        _num(w["period_s"], f"{where}.period_s", lo=0, lo_open=True)
    for k in ("duty", "soft"):
        if k in w:
            if w["shape"] != "square":
                _fail(f"{where}.{k}", "only for square")
            _num(w[k], f"{where}.{k}", 0, 1)
    if "min" in w:
        _num(w["min"], f"{where}.min", 0, 1)


def _profile(p, where):
    _obj(p, where, {"fade_s", *_STATES})
    if "fade_s" in p:
        _num(p["fade_s"], f"{where}.fade_s", lo=0)
    for s in _STATES:
        if s in p:
            st = p[s]
            _obj(st, f"{where}.{s}", {"tint", "level", "wave"}, ("tint", "level"))
            _vec3(st["tint"], f"{where}.{s}.tint", lo=0)
            _num(st["level"], f"{where}.{s}.level", lo=0)
            if "wave" in st:
                _wave(st["wave"], f"{where}.{s}.wave")


GLOW_SRCS = ("emissive", "texture", "flat")


def _glow(g, where):
    """Spec §11.2: what glows (`src`) and a per-shape multiplier (`scale`).
    The colour, level and pulse come from the emitter's profile."""
    _obj(g, where, {"src", "scale"}, ("src",))
    _enum(g["src"], f"{where}.src", GLOW_SRCS)
    if "scale" in g:
        _num(g["scale"], f"{where}.scale", lo=0)


def _light(l, where):
    _obj(l, where, {"position", "direction", "inner_deg", "outer_deg", "range",
                    "intensity", "light_scale"}, ("position", "direction"))
    _vec3(l["position"], f"{where}.position")
    _vec3(l["direction"], f"{where}.direction")
    if sum(c * c for c in l["direction"]) < 1e-12:
        _fail(f"{where}.direction", "must be non-zero")
    inner = l.get("inner_deg", 0.0)
    outer = l.get("outer_deg", 90.0)
    _num(inner, f"{where}.inner_deg", 0, 90)
    _num(outer, f"{where}.outer_deg", 0, 90)
    if inner > outer:
        _fail(f"{where}.inner_deg", "must be <= outer_deg")
    if "range" in l:
        _num(l["range"], f"{where}.range", lo=0, lo_open=True)
    for k in ("intensity", "light_scale"):
        if k in l:
            _num(l[k], f"{where}.{k}", lo=0)


def validate(doc) -> dict:
    _obj(doc, "$", {"format", "source", "profiles", "shapes"},
         ("format", "profiles", "shapes"))
    if doc["format"] != FORMAT:
        _fail("$.format", f"must be {FORMAT}")
    if "source" in doc and not isinstance(doc["source"], str):
        _fail("$.source", "must be a string")
    if not isinstance(doc["profiles"], dict):
        _fail("$.profiles", "must be an object")
    for name, p in doc["profiles"].items():
        _profile(p, f"$.profiles.{name}")
    if not isinstance(doc["shapes"], dict):
        _fail("$.shapes", "must be an object")
    for key, s in doc["shapes"].items():
        where = f"$.shapes.{key}"
        _obj(s, where, {"block", "name", "material", "emitter"}, ("block", "name"))
        if isinstance(s["block"], bool) or not isinstance(s["block"], int) or s["block"] < 0:
            _fail(f"{where}.block", "must be a non-negative integer")
        if not isinstance(s["name"], str):
            _fail(f"{where}.name", "must be a string")
        if key != f"{s['block']}:{s['name']}":
            _fail(where, "key must be '<block>:<name>'")
        if "material" in s:
            _obj(s["material"], f"{where}.material", {"roughness", "metalness"})
            for k, v in s["material"].items():
                _num(v, f"{where}.material.{k}", 0, 1)
        if "emitter" in s:
            e = s["emitter"]
            _obj(e, f"{where}.emitter", {"profile", "phase", "glow", "light"})
            if "profile" in e and e["profile"] not in doc["profiles"]:
                _fail(f"{where}.emitter.profile", f"no profile named {e['profile']!r}")
            if "phase" in e:
                _num(e["phase"], f"{where}.emitter.phase", 0, 1)
            if "glow" in e:
                _glow(e["glow"], f"{where}.emitter.glow")
            if "light" in e:
                _light(e["light"], f"{where}.emitter.light")
    return doc


# ── load + match ────────────────────────────────────────────────────────────

@dataclass
class LoadResult:
    doc: dict
    path: Optional[Path]
    error: Optional[str]


def load(content_hash, source) -> LoadResult:
    """The bridge's document, an empty one when no file exists, or -- when the
    file exists but is unreadable or invalid -- an empty one WITH the path and
    the error, so the editor can refuse to overwrite it."""
    path = find(content_hash)
    if path is None:
        return LoadResult(empty_doc(source), None, None)
    try:
        doc = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:      # JSONDecodeError and BridgeLightingError are ValueErrors
        return LoadResult(empty_doc(source), path, f"{path.name}: {e}")
    return LoadResult(doc, path, None)


def match_shapes(doc, meshes):
    """{shape_key: mesh_index} for every entry whose block holds a shape of
    the same name; one warning per entry that does not -- never applied to a
    different shape."""
    by_block = {m["block"]: m for m in meshes if m["block"] >= 0}
    matched, warnings = {}, []
    for key, s in doc["shapes"].items():
        m = by_block.get(s["block"])
        if m is None:
            warnings.append(f"{key}: no shape at block {s['block']}; skipped")
        elif m["name"] != s["name"]:
            warnings.append(f"{key}: block {s['block']} is {m['name']!r}, "
                            f"file says {s['name']!r}; skipped")
        else:
            matched[key] = m["mesh"]
    return matched, warnings
