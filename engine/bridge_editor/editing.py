"""Pure document edits for the Bridge Editor (spec 2026-10-08-bridge-emitters
§13). Every value is clamped to the schema before it enters the document
(§12.3), so a save can never be refused for something the editor wrote."""
import copy
import math

from engine.bridge_editor import lighting_doc as ld

MIN_PERIOD_S = 0.05
MAX_EMISSION = 16.0           # the slider runs 0-4; typing goes higher, to this
MAX_TRANSITION_S = 10.0
MAX_ROOM_LIGHT = 4.0
LIGHT_INNER_DEG, LIGHT_OUTER_DEG, LIGHT_RANGE = 30.0, 60.0, 200.0
LIGHT_INTENSITY = 2000.0
STRIP_INTENSITY = 40.0        # surface brightness (spec §16.1): a thin strip needs a lot
PANEL_INTENSITY = 2.0
STRIP_OFFSET = 1.0            # out from the surface, so a strip on a flat panel lights it
_LIGHT_MIN_RANGE = 0.01
_WAVE_DEFAULTS = {"sine": {}, "square": {"duty": 0.5, "soft": 0.0}}
# Fields each shape's validator accepts (spec §16.1/§16.4); set_light drops
# any other field for that shape so an edit can never write a document the
# validator -- and so a save -- would refuse.
_SHAPE_FIELDS = {
    "spot": {"inner_deg", "outer_deg", "range", "intensity"},
    "strip": {"edge", "start", "end", "offset", "range", "intensity"},
    "panel": {"x0", "x1", "y0", "y1", "offset", "range", "intensity"},
}


def _num(raw, lo=None, hi=None):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _key(block, name):
    return f"{block}:{name}"


def _prune(doc, block, name):
    o = doc["objects"].get(_key(block, name))
    if o is not None and set(o) == {"block", "name"}:
        del doc["objects"][_key(block, name)]


def link(doc, block, name, material):
    if material and material not in doc["materials"]:
        return
    o = ld.object_entry(doc, block, name)
    if material:
        o["material"] = material
    else:
        o.pop("material", None)
        _prune(doc, block, name)


def new_material(doc, block, name, texture=None):
    """An empty material linked to this object: for a textured object a
    variant of its texture (`<texture> 2`, ...: a material belongs to one
    texture, Mark 2026-10-11), else `material N`."""
    if texture:
        stem, n = ld.texture_stem(texture), 2
        while f"{stem} {n}" in doc["materials"]:
            n += 1
        mat = f"{stem} {n}"
        doc["materials"][mat] = {"texture": ld.texture_key(texture)}
    else:
        n = 1
        while f"material {n}" in doc["materials"]:
            n += 1
        mat = f"material {n}"
        doc["materials"][mat] = {}
    link(doc, block, name, mat)
    return mat


def texture_material(doc, texture):
    """The material of `texture` (each TGA is a material, Mark 2026-10-11),
    made empty and named after the texture the first time it is needed."""
    key = ld.texture_key(texture)
    textures = doc.setdefault("textures", {})
    if key not in textures:
        name = ld.free_name(doc, ld.texture_stem(texture))
        doc["materials"][name] = {"texture": key}
        textures[key] = name
    return textures[key]


def duplicate(doc, block, name, current=None):
    """Copy `current` (default: the object's own link) -- e.g. its texture's
    material -- and link this object alone to the copy."""
    cur = current or doc["objects"].get(_key(block, name), {}).get("material")
    if not cur or cur not in doc["materials"]:
        return None
    new = f"{cur} copy"
    while new in doc["materials"]:
        new = f"{new} copy"
    doc["materials"][new] = copy.deepcopy(doc["materials"][cur])
    link(doc, block, name, new)
    return new


def rename(doc, old, new):
    new = new.strip()
    if not new:
        return "Rename refused: empty name"
    if new == old:
        return None
    if new in doc["materials"]:
        return f"Rename refused: a material named {new!r} exists"
    doc["materials"][new] = doc["materials"].pop(old)
    for o in doc["objects"].values():
        if o.get("material") == old:
            o["material"] = new
    for tex, mat in doc.get("textures", {}).items():
        if mat == old:
            doc["textures"][tex] = new
    return None


def set_finish(mat, ch, raw):
    """roughness/metalness 0-1; emission 0-MAX_EMISSION (spec §14: the
    Finish emission level, Mark 2026-10-12)."""
    if ch in ("roughness", "metalness"):
        v = _num(raw, 0.0, 1.0)
    elif ch == "emission":
        v = _num(raw, 0.0, MAX_EMISSION)
    else:
        return
    if v is not None:
        mat[ch] = v


def clear_finish(mat, ch):
    mat.pop(ch, None)


def set_room_light(doc, state, raw):
    """The bridge's room light for one state (Mark 2026-10-12), 0-MAX."""
    v = _num(raw, 0.0, MAX_ROOM_LIGHT)
    if state in ld.STATES and v is not None:
        doc.setdefault("room_light", {})[state] = v


def clear_room_light(doc, state):
    """Back to the default for that state (0 on a bridge with lights)."""
    room = doc.get("room_light", {})
    room.pop(state, None)
    if not room:
        doc.pop("room_light", None)


def set_emission_source(mat, raw):
    """What glows on a texture with no `_emissive` map: own texture or flat."""
    if raw in ld.EMISSION_SOURCES:
        mat["emission_source"] = raw


def add_modifier(mat, kind, state):
    scope = [state] if state in ld.STATES else []
    if kind == "state":
        m = {"type": "state", "scope": scope, "tint": [1, 1, 1], "level": 1.0}
    elif kind == "animation":
        m = {"type": "animation", "scope": scope, "shape": "sine", "period_s": 2.0,
             "min": 0.0, "phase": 0.0}
    elif kind == "transition":
        m = {"type": "transition", "scope": scope, "seconds": ld.DEFAULT_FADE_S}
    else:
        return
    mat.setdefault("modifiers", []).append(m)


def _mod(mat, i):
    mods = mat.get("modifiers", [])
    return mods[i] if 0 <= i < len(mods) else None


def remove_modifier(mat, i):
    if _mod(mat, i) is not None:
        del mat["modifiers"][i]


def toggle_scope(mat, i, state):
    m = _mod(mat, i)
    if m is None or state not in ld.STATES:
        return
    if state in m["scope"]:
        m["scope"].remove(state)
    else:
        m["scope"] = [s for s in ld.STATES if s in m["scope"] or s == state]


def set_modifier(mat, i, field, raw):
    m = _mod(mat, i)
    if m is None:
        return
    if m["type"] == "transition":
        if field == "seconds":
            v = _num(raw, 0.0, MAX_TRANSITION_S)
            if v is not None:
                m["seconds"] = v
        return
    if m["type"] == "state":
        if field == "tint":
            try:
                rgb = [max(0.0, float(c)) for c in str(raw).split(",")]
            except ValueError:
                return
            if len(rgb) != 3 or not all(math.isfinite(c) for c in rgb):
                return
            top = max(rgb)
            m["tint"] = [round(c / top, 4) for c in rgb] if top > 0 else [0.0, 0.0, 0.0]
        elif field == "level":
            v = _num(raw, lo=0.0)
            if v is not None:
                m["level"] = v
        elif field == "glows":
            # Spec §16.9: absent = glows (the default); false = lights only.
            if raw == "false":
                m["glows"] = False
            elif raw == "true":
                m.pop("glows", None)
        return
    if field == "shape" and raw in _WAVE_DEFAULTS:
        keep = {k: m[k] for k in ("type", "scope", "period_s", "min", "phase") if k in m}
        extra = {k: m.get(k, d) for k, d in _WAVE_DEFAULTS[raw].items()}
        m.clear()
        m.update(keep, shape=raw, **extra)
    elif field == "period_s":
        v = _num(raw, lo=MIN_PERIOD_S)
        if v is not None:
            m["period_s"] = v
    elif field in ("min", "phase") or (field in ("duty", "soft") and m["shape"] == "square"):
        v = _num(raw, 0.0, 1.0)
        if v is not None:
            m[field] = v


def add_light(doc, block, name, position, direction):
    o = ld.object_entry(doc, block, name)
    o.setdefault("lights", []).append({
        "position": list(position), "direction": list(direction),
        "inner_deg": LIGHT_INNER_DEG, "outer_deg": LIGHT_OUTER_DEG,
        "range": LIGHT_RANGE, "intensity": LIGHT_INTENSITY})


def snap_light(light, position):
    """Edge snap (§16.8): a strip snaps to the sharp edge nearest the clicked
    point (edge_snap.snap); anything else is left alone."""
    if light.get("shape") == "strip":
        light["anchor"] = [float(c) for c in position]


def unsnap_light(light):
    light.pop("anchor", None)


def add_area_light(doc, block, name, shape, anchor=None):
    """A strip or a panel (spec §16.4). A strip given `anchor` -- the click
    that selected the object -- snaps to the sharp edge nearest it (§16.8);
    without one it sits on the object's top box edge. The rectangles are
    recomputed from the object at load."""
    o = ld.object_entry(doc, block, name)
    if shape == "strip":
        light = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0,
                 "offset": STRIP_OFFSET, "range": LIGHT_RANGE, "intensity": STRIP_INTENSITY}
        if anchor is not None:
            light["anchor"] = [float(c) for c in anchor]
    elif shape == "panel":
        light = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0], "offset": 0.0,
                 "range": LIGHT_RANGE, "intensity": PANEL_INTENSITY}
    else:
        return
    o.setdefault("lights", []).append(light)


def remove_light(doc, block, name, i):
    o = doc["objects"].get(_key(block, name))
    if not o or not (0 <= i < len(o.get("lights", []))):
        return
    del o["lights"][i]
    if not o["lights"]:
        del o["lights"]
    _prune(doc, block, name)


def set_light(light, field, raw):
    if field not in _SHAPE_FIELDS.get(light.get("shape", "spot"), ()):
        return
    if field == "edge":
        if raw in ld.EDGES:
            light["edge"] = raw
        return
    v = _num(raw)
    if v is None:
        return
    if field in ("inner_deg", "outer_deg"):
        v = min(90.0, max(0.0, v))
        light[field] = v
        if field == "inner_deg" and light.get("outer_deg", 90.0) < v:
            light["outer_deg"] = v
        elif field == "outer_deg" and v < light.get("inner_deg", 0.0):
            light["inner_deg"] = v
    elif field in ("start", "end"):
        v = min(1.0, max(0.0, v))
        light[field] = v
        if field == "start" and light.get("end", 1.0) < v:
            light["end"] = v
        elif field == "end" and v < light.get("start", 0.0):
            light["start"] = v
    elif field in ("x0", "x1", "y0", "y1"):
        axis, i = field[0], int(field[1])
        span = [float(c) for c in light.get(axis, [0.0, 1.0])]
        span[i] = min(1.0, max(0.0, v))
        if span[0] > span[1]:
            span[1 - i] = span[i]
        light[axis] = span
    elif field == "offset":
        light[field] = v
    elif field == "range":
        light[field] = max(_LIGHT_MIN_RANGE, v)
    elif field == "intensity":
        light[field] = max(0.0, v)
