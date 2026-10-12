"""Object lights (spec 2026-10-08-bridge-emitters §13.2, §11.4, §14, §16). The
rows are built ONCE per push by `build()` -- every light of every matched
object, mesh order, with green and yellow/red probe-capture colours baked in
-- so a state change or a pulse never recaptures the probes; `live()` gives
this frame's radiance for the built rows, in their own order. Spots, strip
segments and panels share ONE budget of MAX_LIGHTS rows (§16.3, §16.8): a
spot costs one row, a strip or panel costs one row per rectangle (a snapped
strip can cost up to MAX_SEGMENTS), and a light that does not fit whole is
dropped with a warning -- never cut short. A light's colour follows the glow
of its mesh's resolved material (the object's link, else its texture's;
`mapped` = the meshes whose texture has an `_emissive` map, for the
unset-emission default), display -> linear by ^2.2; a material that sets no
glow lights steady white. A capture colour is the steady value in that
state, 0 when an animation runs there. A strip or panel's rectangle comes
from its object's frame (light_shapes, §16.2) via edge_snap."""
from dataclasses import dataclass, field

from engine.bridge_editor import behaviour, edge_snap

MAX_LIGHTS = 32
DEFAULT_INTENSITY = 2000.0
DEFAULT_AREA_INTENSITY = 1.0
DEFAULT_RANGE = 200.0
GAMMA = 2.2
# Safely above the native binding's own drop threshold (1e-8, host_bindings.cc
# set_bridge_area_lights) -- a rectangle this size or larger always survives
# there once Python has already kept it (review finding 1).
MIN_AREA = 1e-6


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _is_spot(light):
    return light.get("shape", "spot") == "spot"


def _intensity(light):
    default = DEFAULT_INTENSITY if _is_spot(light) else DEFAULT_AREA_INTENSITY
    return light.get("intensity", default) * light.get("light_scale", 1.0)


def _material(doc, name):
    """The material a light's colour follows: its mesh's (resolved), unless
    it sets no glow -- a finish-only material lights like no material at
    all: steady white (spec §13.2; review C1: the upgraded DBridge 299/319
    lights went dark)."""
    mat = doc["materials"].get(name) if name else None
    return mat if mat is not None and behaviour.drives_glow(mat) else behaviour.WHITE


def _capture(mat, state, has_map):
    if any(m["type"] == "animation" and state in m["scope"]
           for m in mat.get("modifiers", ())):
        return (0.0, 0.0, 0.0)
    rgb, _ = behaviour.output(mat, state, 0.0, has_map)
    return to_linear(rgb)


def _cross_len(a, b):
    cx = a[1] * b[2] - a[2] * b[1]
    cy = a[2] * b[0] - a[0] * b[2]
    cz = a[0] * b[1] - a[1] * b[0]
    return (cx * cx + cy * cy + cz * cz) ** 0.5


@dataclass
class Built:
    """The static rows for one push, and what their live colours follow."""
    spot_rows: list = field(default_factory=list)
    area_rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    spot_lit: list = field(default_factory=list)    # (light, material, has_map) per spot row
    area_lit: list = field(default_factory=list)    # (light, material, has_map) per area row


def build(doc, matched, resolved, frame_for=lambda mesh: None, mapped=frozenset()) -> Built:
    """Every light of every matched object, mesh order, as renderer rows (spec
    §16.3, §16.8). The budget of MAX_LIGHTS counts ROWS: a spot is one, a
    strip or panel one per rectangle (a snapped strip one per edge segment).
    A light that does not fit whole is dropped with a warning -- never cut
    short -- and a later light that still fits is kept. A strip or panel
    needs its object's frame (`frame_for(mesh)`); without one it is skipped
    with a warning."""
    out = Built()
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mesh = matched[key]
        mat = _material(doc, resolved.get(mesh))
        has_map = mesh in mapped
        for i, light in enumerate(obj.get("lights", ())):
            label = f"{key} light {i + 1}"
            rects = None
            if not _is_spot(light):
                fr = frame_for(mesh)
                if fr is None:
                    out.warnings.append(f"{label}: no geometry for its object; skipped")
                    continue
                if light.get("anchor") and edge_snap.snap(fr, light["anchor"]) is None:
                    out.warnings.append(
                        f"{label}: no sharp edge near its snap point; using its edge chips")
                rects = []
                for r in edge_snap.light_rects(light, fr):
                    if _cross_len(r.half_u, r.half_v) < MIN_AREA:
                        out.warnings.append(f"{label}: zero size; skipped")
                    else:
                        rects.append(r)
                if not rects:
                    continue
            cost = 1 if rects is None else len(rects)
            used = len(out.spot_rows) + len(out.area_rows)
            if used + cost > MAX_LIGHTS:
                out.warnings.append(f"{label}: dropped (needs {cost} of the {MAX_LIGHTS} "
                                    f"bridge lights, {MAX_LIGHTS - used} left)")
                continue
            green = _capture(mat, "green", has_map)
            alert = _capture(mat, "yellow", has_map)
            if rects is None:
                out.spot_rows.append((tuple(light["position"]), tuple(light["direction"]),
                                      light.get("inner_deg", 30), light.get("outer_deg", 60),
                                      light.get("range", DEFAULT_RANGE), green,
                                      _intensity(light), green, alert))
                out.spot_lit.append((light, mat, has_map))
                continue
            for r in rects:
                out.area_rows.append((r.centre, r.half_u, r.half_v,
                                      light.get("range", DEFAULT_RANGE), green,
                                      _intensity(light), green, alert, r.joins))
                out.area_lit.append((light, mat, has_map))
    return out


def live(built, fade, t):
    """This frame's LINEAR radiance per spot row and per area row, in the
    rows' own order (spec §11.4): the material's output through the state
    fade, ^2.2, x the light's intensity."""
    def colours(lit):
        out = []
        for light, mat, has_map in lit:
            rgb, _k = fade.output(mat, t, has_map)
            k = _intensity(light)
            out.append(tuple(c * k for c in to_linear(rgb)))
        return out
    return colours(built.spot_lit), colours(built.area_lit)
