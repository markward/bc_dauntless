"""Per-bridge lighting document (spec 2026-10-08-bridge-emitters §7, §13.4, §16).

One JSON file per bridge NIF, keyed by the NIF's content hash: a `materials`
library (finish, emission, scoped Emitter/Animation modifiers) and `objects`
(a material link and lights). Only references and parameters -- never BC
geometry. Unknown keys are REJECTED: a typo must fail loudly. `format: 1`
files (per-shape profiles) are upgraded on load."""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine import paths

MOD_REL = "dauntless/bridge_lighting"



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


def _v1_wave(w, where):
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


def _v1_profile(p, where):
    _obj(p, where, {"fade_s", *_V1_STATES})
    if "fade_s" in p:
        _num(p["fade_s"], f"{where}.fade_s", lo=0)
    for s in _V1_STATES:
        if s in p:
            st = p[s]
            _obj(st, f"{where}.{s}", {"tint", "level", "wave"}, ("tint", "level"))
            _vec3(st["tint"], f"{where}.{s}.tint", lo=0)
            _num(st["level"], f"{where}.{s}.level", lo=0)
            if "wave" in st:
                _v1_wave(st["wave"], f"{where}.{s}.wave")


GLOW_SRCS = ("emissive", "texture", "flat")


def _v1_glow(g, where):
    """Spec §11.2: what glows (`src`) and a per-shape multiplier (`scale`).
    The colour, level and pulse come from the emitter's profile."""
    _obj(g, where, {"src", "scale"}, ("src",))
    _enum(g["src"], f"{where}.src", GLOW_SRCS)
    if "scale" in g:
        _num(g["scale"], f"{where}.scale", lo=0)


LIGHT_SHAPES = ("spot", "strip", "panel")
EDGES = ("top", "bottom", "left", "right")


def _light(l, where):
    """A light (spec §13.2, §16.1): a `spot` (also when `shape` is absent),
    or a `strip` / `panel` cut from the object's front rectangle -- which
    stores parameters only, never coordinates."""
    if not isinstance(l, dict):
        _fail(where, "must be an object")
    shape = l.get("shape", "spot")
    _enum(shape, f"{where}.shape", LIGHT_SHAPES)
    if shape == "spot":
        _spot(l, where)
    else:
        _area_light(l, where, shape)


def _spot(l, where):
    _obj(l, where, {"shape", "position", "direction", "inner_deg", "outer_deg", "range",
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


def _span(v, where):
    if not isinstance(v, list) or len(v) != 2:
        _fail(where, "must be [from, to]")
    _num(v[0], f"{where}[0]", 0, 1)
    _num(v[1], f"{where}[1]", 0, 1)
    if v[0] > v[1]:
        _fail(where, "from must be <= to")


def _area_light(l, where, shape):
    common = {"shape", "offset", "range", "intensity", "light_scale"}
    if shape == "strip":
        _obj(l, where, common | {"edge", "start", "end", "anchor"}, ("edge",))
        _enum(l["edge"], f"{where}.edge", EDGES)
        if "anchor" in l:           # edge snap (§16.8): the clicked point it snaps from
            _vec3(l["anchor"], f"{where}.anchor")
        start, end = l.get("start", 0.0), l.get("end", 1.0)
        _num(start, f"{where}.start", 0, 1)
        _num(end, f"{where}.end", 0, 1)
        if start > end:
            _fail(f"{where}.start", "must be <= end")
    else:
        _obj(l, where, common | {"x", "y"})
        for k in ("x", "y"):
            if k in l:
                _span(l[k], f"{where}.{k}")
    if "offset" in l:
        _num(l["offset"], f"{where}.offset")
    if "range" in l:
        _num(l["range"], f"{where}.range", lo=0, lo_open=True)
    for k in ("intensity", "light_scale"):
        if k in l:
            _num(l[k], f"{where}.{k}", lo=0)


def _validate_v1(doc) -> dict:
    _obj(doc, "$", {"format", "source", "profiles", "shapes"},
         ("format", "profiles", "shapes"))
    if doc["format"] != 1:
        _fail("$.format", "must be 1")
    if "source" in doc and not isinstance(doc["source"], str):
        _fail("$.source", "must be a string")
    if not isinstance(doc["profiles"], dict):
        _fail("$.profiles", "must be an object")
    for name, p in doc["profiles"].items():
        _v1_profile(p, f"$.profiles.{name}")
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
                _v1_glow(e["glow"], f"{where}.emitter.glow")
            if "light" in e:
                _light(e["light"], f"{where}.emitter.light")
    return doc


FORMAT = 4
STATES = ("offline", "green", "yellow", "red", "special")
# Emission is a Finish level (spec §14, Mark 2026-10-12): the texture's
# `_emissive` map glows when it has one; `emission_source` is what glows on a
# texture without one -- its own texture, or a flat colour.
EMISSION_SOURCES = ("texture", "flat")
MODIFIERS = ("state", "animation", "transition")
DEFAULT_FADE_S = 0.5          # a state change blends this long unless a Transition says
_WAVES = ("sine", "square")


def empty_doc(source) -> dict:
    return {"format": FORMAT, "source": str(source), "materials": {}, "objects": {}}


def object_entry(doc, block, name) -> dict:
    key = f"{block}:{name}"
    entry = doc["objects"].get(key)
    if entry is None:
        entry = {"block": int(block), "name": str(name)}
        doc["objects"][key] = entry
    return entry


def _scope(v, where):
    if not isinstance(v, list) or any(s not in STATES for s in v) or len(set(v)) != len(v):
        _fail(where, f"must be a list of distinct states from {', '.join(STATES)}")


def _modifier(m, where):
    if not isinstance(m, dict) or m.get("type") not in MODIFIERS:
        _fail(f"{where}.type", f"must be one of {', '.join(MODIFIERS)}")
    if m["type"] == "state":
        _obj(m, where, {"type", "scope", "tint", "level"}, ("scope", "tint", "level"))
        _vec3(m["tint"], f"{where}.tint", lo=0)
        _num(m["level"], f"{where}.level", lo=0)
    elif m["type"] == "transition":
        _obj(m, where, {"type", "scope", "seconds"}, ("scope", "seconds"))
        _num(m["seconds"], f"{where}.seconds", lo=0)
    else:
        _obj(m, where, {"type", "scope", "shape", "period_s", "min", "duty", "soft", "phase"},
             ("scope", "shape", "period_s"))
        _enum(m["shape"], f"{where}.shape", _WAVES)
        _num(m["period_s"], f"{where}.period_s", lo=0, lo_open=True)
        for k in ("duty", "soft"):
            if k in m:
                if m["shape"] != "square":
                    _fail(f"{where}.{k}", "only for square")
                _num(m[k], f"{where}.{k}", 0, 1)
        for k in ("min", "phase"):
            if k in m:
                _num(m[k], f"{where}.{k}", 0, 1)
    _scope(m["scope"], f"{where}.scope")


def _material(m, where):
    _obj(m, where, {"texture", "roughness", "metalness", "emission", "emission_source",
                    "modifiers"})
    if "texture" in m and not isinstance(m["texture"], str):
        _fail(f"{where}.texture", "must be a string (the texture's file name, case-folded)")
    for ch in ("roughness", "metalness"):
        if ch in m:
            _num(m[ch], f"{where}.{ch}", 0, 1)
    if "emission" in m:
        _num(m["emission"], f"{where}.emission", lo=0)
    if "emission_source" in m:
        _enum(m["emission_source"], f"{where}.emission_source", EMISSION_SOURCES)
    if "modifiers" in m:
        if not isinstance(m["modifiers"], list):
            _fail(f"{where}.modifiers", "must be a list")
        for i, mod in enumerate(m["modifiers"]):
            _modifier(mod, f"{where}.modifiers[{i}]")


def has_lights(doc) -> bool:
    return any(o.get("lights") for o in doc.get("objects", {}).values())


def room_light(doc, state) -> Optional[float]:
    """The room light (the bridge ambient's multiplier) for `state` (Mark
    2026-10-12): the bridge's own `room_light` level when it sets one; else
    0 when the bridge defines lights of its own (they light the room);
    else None -- the engine default (engine/bridge_lighting.py)."""
    own = doc.get("room_light", {}).get(state)
    if own is not None:
        return float(own)
    return 0.0 if has_lights(doc) else None


def texture_key(name) -> str:
    """A texture's identity in `textures`: its file name, case-folded (BC
    paths mix case and separators)."""
    return str(name).replace("\\", "/").rsplit("/", 1)[-1].lower()


def texture_stem(name) -> str:
    """The display name a texture's material gets: the file name as written,
    without its extension."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def validate(doc) -> dict:
    _obj(doc, "$", {"format", "source", "materials", "objects", "textures", "room_light"},
         ("format", "materials", "objects"))
    if doc["format"] != FORMAT:
        _fail("$.format", f"must be {FORMAT}")
    if "source" in doc and not isinstance(doc["source"], str):
        _fail("$.source", "must be a string")
    if not isinstance(doc["materials"], dict):
        _fail("$.materials", "must be an object")
    for name, m in doc["materials"].items():
        _material(m, f"$.materials.{name}")
    if not isinstance(doc["objects"], dict):
        _fail("$.objects", "must be an object")
    for key, o in doc["objects"].items():
        where = f"$.objects.{key}"
        _obj(o, where, {"block", "name", "material", "lights"}, ("block", "name"))
        if isinstance(o["block"], bool) or not isinstance(o["block"], int) or o["block"] < 0:
            _fail(f"{where}.block", "must be a non-negative integer")
        if not isinstance(o["name"], str):
            _fail(f"{where}.name", "must be a string")
        if key != f"{o['block']}:{o['name']}":
            _fail(where, "key must be '<block>:<name>'")
        if "material" in o and o["material"] not in doc["materials"]:
            _fail(f"{where}.material", f"no material named {o['material']!r}")
        if "lights" in o:
            if not isinstance(o["lights"], list):
                _fail(f"{where}.lights", "must be a list")
            for i, light in enumerate(o["lights"]):
                _light(light, f"{where}.lights[{i}]")
    if "room_light" in doc:
        if not isinstance(doc["room_light"], dict):
            _fail("$.room_light", "must be an object of state: level")
        for state, v in doc["room_light"].items():
            if state not in STATES:
                _fail(f"$.room_light.{state}", f"must be one of {', '.join(STATES)}")
            _num(v, f"$.room_light.{state}", lo=0)
    if "textures" in doc:
        if not isinstance(doc["textures"], dict):
            _fail("$.textures", "must be an object")
        for tex, name in doc["textures"].items():
            if name not in doc["materials"]:
                _fail(f"$.textures.{tex}", f"no material named {name!r}")
            own = doc["materials"][name].get("texture")
            if own is not None and own != tex:
                _fail(f"$.textures.{tex}", f"material {name!r} is for {own}")
    return doc


# ── format 1 -> 2 (spec §13.4) ───────────────────────────────────────────────

# v1 glow src -> v2 `without_map` ("emissive" needed a map, which v2 uses
# automatically; its fallback is the own texture).
_V1_SRC = {"emissive": "texture", "texture": "texture", "flat": "flat"}
_V1_STATES = ("green", "yellow", "red")
_V1_WHITE = {s: {"tint": [1, 1, 1], "level": 1} for s in _V1_STATES}


def _merge(mods, mod, state):
    for m in mods:
        if {k: v for k, v in m.items() if k != "scope"} == mod:
            m["scope"].append(state)
            return
    mods.append(dict(mod, scope=[state]))


def _v1_modifiers(profile, phase):
    emitters, animations = [], []
    for s in _V1_STATES:
        st = profile.get(s)
        if st is None:
            continue
        _merge(emitters, {"type": "emitter", "tint": list(st["tint"]), "level": st["level"]}, s)
        w = st.get("wave")
        if w and w["shape"] != "steady":
            a = {"type": "animation", **{k: v for k, v in w.items()}, "phase": phase}
            _merge(animations, a, s)
    return emitters + animations


def _v3_to_v4(doc) -> dict:
    """`format: 3` -> 4 (spec §16.1): lights gained `shape`; a light without
    one is a spot, which is every light a format-3 file holds."""
    doc = json.loads(json.dumps(doc))
    doc["format"] = 4
    return doc


def upgrade(doc) -> dict:
    """An older document as the current format (1 -> 2 -> 3 -> 4), or the
    document itself when it is not an older format."""
    if not isinstance(doc, dict):
        return doc
    if doc.get("format") == 1:
        return _v3_to_v4(_v2_to_v3(_v1_to_v2(doc)))
    if doc.get("format") == 2:
        return _v3_to_v4(_v2_to_v3(doc))
    if doc.get("format") == 3:
        return _v3_to_v4(doc)
    return doc


def _v2_to_v3(doc) -> dict:
    """`format: 2` -> 3 (spec §14, Mark 2026-10-12), every state looking the
    same: emitters become State modifiers with the old emission strength
    folded into their levels, and the base emission is 0 -- a state no
    emitter covered was dark; `without_map` becomes `emission_source`; a
    fade other than the 0.5 s default becomes a Transition on every state.
    Strength or fade on a material with no emitters did nothing and is
    dropped. (Lossy only for a v1 profiled light with no glow, strength 0:
    its light now follows levels of 0.)"""
    doc = json.loads(json.dumps(doc))
    if not isinstance(doc.get("materials"), dict):
        return doc
    for mat in doc["materials"].values():
        if not isinstance(mat, dict):
            continue
        e = mat.pop("emission", {})
        e = e if isinstance(e, dict) else {}
        strength = e.get("strength", 1)
        if e.get("without_map", "texture") != "texture":
            mat["emission_source"] = e["without_map"]
        fade = mat.pop("fade_s", DEFAULT_FADE_S)
        mods = mat.get("modifiers")
        if not isinstance(mods, list) or not any(
                isinstance(m, dict) and m.get("type") == "emitter" for m in mods):
            continue
        for m in mods:
            if isinstance(m, dict) and m.get("type") == "emitter":
                m["type"] = "state"
                m["level"] = round(m.get("level", 0) * strength, 6)
        mat["emission"] = 0
        if fade != DEFAULT_FADE_S:
            mods.append({"type": "transition", "scope": list(STATES), "seconds": fade})
    doc["format"] = 3
    return doc


def _v1_to_v2(doc) -> dict:
    """A validated-shape `format: 1` document as `format: 2` (spec §13.4):
    each shape's material overrides + glow source/scale + profile (+ phase)
    form one material; identical PROFILED materials are shared, named after
    the profile (`<profile> 2`, ... on a clash); every other object gets its
    own `material N`, never merged; the light becomes lights[0]."""
    doc = _validate_v1(doc)
    out = dict(empty_doc(doc.get("source", "")), format=2)
    by_sig = {}
    for key in sorted(doc["shapes"], key=lambda k: (doc["shapes"][k]["block"], k)):
        s = doc["shapes"][key]
        em = s.get("emitter", {})
        mat = {ch: v for ch, v in s.get("material", {}).items()}
        prof_name = em.get("profile")
        prof = doc["profiles"][prof_name] if prof_name else None
        glow = em.get("glow")
        if glow is not None or (prof is not None and "light" in em):
            # No v1 glow (a profiled light only): strength 0 -- no glow, the
            # light still follows the emitters.
            emission = {"without_map": _V1_SRC[glow["src"]] if glow else "texture"}
            if glow is None:
                emission["strength"] = 0
            elif glow.get("scale", 1) != 1:
                emission["strength"] = glow["scale"]
            mat["emission"] = emission
            if prof is not None and "fade_s" in prof:
                mat["fade_s"] = prof["fade_s"]
            mat["modifiers"] = _v1_modifiers(prof or _V1_WHITE, em.get("phase", 0.0))
        obj = {"block": s["block"], "name": s["name"]}
        if mat:
            # Only profiled materials share: v1 objects sharing a profile chose
            # to; equal finish-only values are a coincidence, and merging them
            # made one edit land on dozens of unrelated objects.
            sig = json.dumps(mat, sort_keys=True) if prof_name else None
            name = by_sig.get(sig) if sig else None
            if name is None:
                if prof_name:
                    name, n = prof_name, 2
                    while name in out["materials"]:
                        name, n = f"{prof_name} {n}", n + 1
                else:
                    n = 1
                    while f"material {n}" in out["materials"]:
                        n += 1
                    name = f"material {n}"
                if sig:
                    by_sig[sig] = name
                out["materials"][name] = mat
            obj["material"] = name
        if "light" in em:
            obj["lights"] = [dict(em["light"])]
        if len(obj) > 2:
            out["objects"][key] = obj
    return out


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
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = validate(upgrade(raw))
    except (OSError, ValueError) as e:      # JSONDecodeError and BridgeLightingError are ValueErrors
        return LoadResult(empty_doc(source), path, f"{path.name}: {e}")
    return LoadResult(doc, path, None)


def match_shapes(doc, meshes):
    """{shape_key: mesh_index} for every entry whose block holds a shape of
    the same name; one warning per entry that does not -- never applied to a
    different shape."""
    by_block = {m["block"]: m for m in meshes if m["block"] >= 0}
    matched, warnings = {}, []
    for key, s in doc["objects"].items():
        m = by_block.get(s["block"])
        if m is None:
            warnings.append(f"{key}: no shape at block {s['block']}; skipped")
        elif m["name"] != s["name"]:
            warnings.append(f"{key}: block {s['block']} is {m['name']!r}, "
                            f"file says {s['name']!r}; skipped")
        else:
            matched[key] = m["mesh"]
    return matched, warnings


# ── texture materials (Mark 2026-10-11: each TGA is a material) ─────────────

def mesh_texture(mesh) -> Optional[str]:
    """A mesh's Base texture as built (host_io.model_identity), or None."""
    tex = mesh.get("textures") or ()
    return tex[0] if tex else None


def resolve(doc, meshes, matched) -> dict:
    """{mesh_index: material name} for every mesh that has one: the object's
    own link wins (only where its name matched, see match_shapes); otherwise
    the material of the mesh's texture (`textures`). Meshes with neither are
    absent -- they render with the defaults."""
    by_mesh = {m["mesh"]: m for m in meshes}
    linked = {}
    for key, mesh in matched.items():
        name = doc["objects"].get(key, {}).get("material")
        if name and fits(doc, name, by_mesh.get(mesh, {})):
            linked[mesh] = name
    by_tex = doc.get("textures", {})
    out = {}
    for m in meshes:
        i = m["mesh"]
        if i in linked:
            out[i] = linked[i]
            continue
        tex = mesh_texture(m)
        name = by_tex.get(texture_key(tex)) if tex else None
        if name:
            out[i] = name
    return out


def fits(doc, name, mesh) -> bool:
    """A material belongs to one texture (Mark 2026-10-11: the TGA is part
    of the material); a link counts only on a mesh of that texture. A
    material with no texture recorded (an upgraded format-1 file) fits any."""
    own = doc["materials"].get(name, {}).get("texture")
    if own is None:
        return True
    tex = mesh_texture(mesh)
    return tex is not None and texture_key(tex) == own


def link_mismatches(doc, meshes, matched) -> list:
    """One warning per link that resolve() ignores: its material is for
    another texture (only a hand-edited file can hold one)."""
    by_mesh = {m["mesh"]: m for m in meshes}
    out = []
    for key in sorted(matched):
        name = doc["objects"][key].get("material")
        mesh = by_mesh.get(matched[key], {})
        if name and not fits(doc, name, mesh):
            tex = mesh_texture(mesh)
            out.append(f"{key}: material {name!r} is for {doc['materials'][name]['texture']}, "
                       f"the object uses {texture_key(tex) if tex else 'no texture'}; ignored")
    return out


def free_name(doc, base) -> str:
    """`base`, or `base 2`, `base 3`, ... -- the first unused material name."""
    name, n = base, 2
    while name in doc["materials"]:
        name, n = f"{base} {n}", n + 1
    return name


def _finish_only(mat) -> bool:
    return set(mat) <= {"roughness", "metalness", "texture"}


def _finish_sig(mat) -> str:
    """Finishes equal when rounded to 0.05 are one surface (slider noise:
    DBridge's Map 9 doors sit at 0.53 and 0.54)."""
    return json.dumps({k: round(v * 20) / 20 for k, v in mat.items() if k != "texture"},
                      sort_keys=True)


def _from_default(mat) -> float:
    return abs(mat.get("roughness", 1.0) - 1.0) + abs(mat.get("metalness", 0.0))


def fold_into_textures(doc, meshes) -> dict:
    """One-off conversion (Mark 2026-10-11): objects linked to a FINISH-ONLY
    material (roughness/metalness, nothing else) fold into a material for
    their texture. Per texture the most common finish among those objects
    wins (finishes equal to 0.05 count as one, taking the first one's value;
    a tie goes to the finish nearest the default, so meshes that adopt it
    change least); each object that differs keeps a link to its own
    `<texture> 2`, `<texture> 3`, ... Profiled materials
    (emission, modifiers, fade) stay linked. Meshes of that texture with no
    link at all adopt the texture's material -- that is the point.

    Mutates `doc`; returns {material: {folded, kept: [keys], adopted}}."""
    matched, _ = match_shapes(doc, meshes)
    by_mesh = {m["mesh"]: m for m in meshes}
    groups = {}
    for key in sorted(matched, key=lambda k: (doc["objects"][k]["block"], k)):
        name = doc["objects"][key].get("material")
        tex = mesh_texture(by_mesh[matched[key]])
        if not name or not tex or not _finish_only(doc["materials"][name]):
            continue
        groups.setdefault(texture_key(tex), (tex, []))[1].append(key)
    linked_meshes = {matched[k] for k, o in doc["objects"].items()
                     if k in matched and o.get("material")}
    report, dropped = {}, set()
    doc.setdefault("textures", {})
    for tkey, (tex, keys) in sorted(groups.items()):
        mats = [doc["materials"][doc["objects"][k]["material"]] for k in keys]
        sigs = [_finish_sig(m) for m in mats]
        counts, rep = {}, {}
        for s, m in zip(sigs, mats):
            counts[s] = counts.get(s, 0) + 1
            rep.setdefault(s, m)               # the first (lowest block) one's value
        win = max(counts, key=lambda s: (counts[s], -_from_default(rep[s]), -sigs.index(s)))
        name = free_name(doc, texture_stem(tex))
        doc["materials"][name] = dict(rep[win], texture=tkey)
        doc["textures"][tkey] = name
        kept, odd = [], {}
        for key, sig in zip(keys, sigs):
            obj = doc["objects"][key]
            dropped.add(obj["material"])
            if sig == win:
                del obj["material"]
                if set(obj) == {"block", "name"}:
                    del doc["objects"][key]
                continue
            if sig not in odd:
                odd[sig] = free_name(doc, texture_stem(tex))
                doc["materials"][odd[sig]] = dict(rep[sig], texture=tkey)
            obj["material"] = odd[sig]
            kept.append(key)
        adopted = sum(1 for m in meshes if m["mesh"] not in linked_meshes
                      and mesh_texture(m) and texture_key(mesh_texture(m)) == tkey)
        report[name] = {"folded": len(keys) - len(kept), "kept": kept, "adopted": adopted}
    in_use = {o.get("material") for o in doc["objects"].values()} | set(doc["textures"].values())
    for name in dropped - in_use:
        del doc["materials"][name]
    if not doc["textures"]:
        del doc["textures"]
    return report


def bind_textures(doc, meshes) -> list:
    """One-off conversion (Mark 2026-10-11: a material belongs to one
    texture): record each material's texture from the objects using it. A
    material used across textures splits -- the texture with the most users
    (a tie: the lowest block) keeps the name, each other texture's objects
    move to a copy `<name> (<texture>)`. Texture-mapped materials take their
    mapping's texture; unused materials are left without one. Mutates
    `doc`; returns one line per split."""
    matched, _ = match_shapes(doc, meshes)
    by_mesh = {m["mesh"]: m for m in meshes}
    users = {}
    for key in sorted(matched, key=lambda k: (doc["objects"][k]["block"], k)):
        name = doc["objects"][key].get("material")
        tex = mesh_texture(by_mesh[matched[key]])
        if name and tex:
            users.setdefault(name, {}).setdefault(texture_key(tex), (tex, []))[1].append(key)
    for tkey, name in doc.get("textures", {}).items():
        doc["materials"][name]["texture"] = tkey
    splits = []
    for name, by_tex in sorted(users.items()):
        order = sorted(by_tex, key=lambda t: -len(by_tex[t][1]))   # stable: block order on a tie
        doc["materials"][name]["texture"] = order[0]
        for tkey in order[1:]:
            tex, keys = by_tex[tkey]
            copy_name = free_name(doc, f"{name} ({texture_stem(tex)})")
            doc["materials"][copy_name] = json.loads(json.dumps(doc["materials"][name]))
            doc["materials"][copy_name]["texture"] = tkey
            for key in keys:
                doc["objects"][key]["material"] = copy_name
            splits.append(f"{name}: {texture_stem(tex)} objects moved to {copy_name!r}")
    return splits
