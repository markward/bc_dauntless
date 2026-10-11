"""Object lights (spec 2026-10-08-bridge-emitters §13.2, §11.4). The spot
LIST is static -- every light of every matched object, mesh order, with its
green and yellow/red probe-capture colours -- so a state change or a pulse
never recaptures the probes; `live_colours` gives the radiance per frame in
the same order. A light's colour follows its object's material (steady white
without one), display -> linear by ^2.2. A capture colour is the steady
value in that state, 0 when an animation runs there."""
from engine.bridge_editor import behaviour

MAX_SPOTS = 32
DEFAULT_INTENSITY = 2000.0
GAMMA = 2.2


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _intensity(light):
    return light.get("intensity", DEFAULT_INTENSITY) * light.get("light_scale", 1.0)


def _material(doc, obj):
    """The material a light's colour follows: the object's, unless it has no
    emitter -- a finish-only material (roughness/metalness) lights like no
    material at all: steady white (spec §13.2; review C1: the upgraded
    DBridge 299/319 lights went dark)."""
    name = obj.get("material")
    mat = doc["materials"].get(name) if name else None
    return mat if mat is not None and behaviour.has_emitter(mat) else behaviour.WHITE


def _lit(doc, matched):
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mat = _material(doc, obj)
        for i, light in enumerate(obj.get("lights", ())):
            if len(out) >= MAX_SPOTS:
                warnings.append(f"{key} light {i + 1}: dropped (more than {MAX_SPOTS} "
                                "bridge lights)")
                continue
            out.append((light, mat))
    return out, warnings


def _capture(mat, state):
    if any(m["type"] == "animation" and state in m["scope"]
           for m in mat.get("modifiers", ())):
        return (0.0, 0.0, 0.0)
    rgb, _ = behaviour.output(mat, state, 0.0)
    return to_linear(rgb)


def spots(doc, matched):
    lit, warnings = _lit(doc, matched)
    out = []
    for light, mat in lit:
        green = _capture(mat, "green")
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", 200), green, _intensity(light),
                    green, _capture(mat, "yellow")))
    return out, warnings


def live_colours(doc, matched, fade, t):
    lit, _ = _lit(doc, matched)
    out = []
    for light, mat in lit:
        rgb, _k = fade.output(mat, t)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
