"""Object lights (spec 2026-10-08-bridge-emitters §13.2, §11.4, §14, §16). The
light LISTS are static -- every light of every matched object, mesh order,
with green and yellow/red probe-capture colours -- so a state change or a
pulse never recaptures the probes; `live_colours` / `live_area_colours`
give the radiance per frame in the same orders. Spots, strips and panels
share ONE budget of MAX_LIGHTS (§16.3). A light's colour follows the glow of
its mesh's resolved material (the object's link, else its texture's;
`mapped` = the meshes whose texture has an `_emissive` map, for the
unset-emission default), display -> linear by ^2.2; a material that sets no
glow lights steady white. A capture colour is the steady value in that
state, 0 when an animation runs there. A strip or panel's rectangle comes
from its object's frame (light_shapes, §16.2)."""
from engine.bridge_editor import behaviour, light_shapes

MAX_LIGHTS = 32
MAX_SPOTS = MAX_LIGHTS          # the old name; the budget is shared now
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


def _lit(doc, matched, resolved, mapped):
    """Every light within the shared budget, mesh order: (light, material,
    has_map, mesh, label); plus one warning per light dropped by the cap."""
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mesh = matched[key]
        mat = _material(doc, resolved.get(mesh))
        for i, light in enumerate(obj.get("lights", ())):
            label = f"{key} light {i + 1}"
            if len(out) >= MAX_LIGHTS:
                warnings.append(f"{label}: dropped (more than {MAX_LIGHTS} bridge lights)")
                continue
            out.append((light, mat, mesh in mapped, mesh, label))
    return out, warnings


def _capture(mat, state, has_map):
    if any(m["type"] == "animation" and state in m["scope"]
           for m in mat.get("modifiers", ())):
        return (0.0, 0.0, 0.0)
    rgb, _ = behaviour.output(mat, state, 0.0, has_map)
    return to_linear(rgb)


def spots(doc, matched, resolved, mapped=frozenset()):
    """The spot rows, and the shared budget's drop warnings (reported here
    only, so a caller that also asks for areas() sees each once)."""
    lit, warnings = _lit(doc, matched, resolved, mapped)
    out = []
    for light, mat, has_map, _mesh, _label in lit:
        if not _is_spot(light):
            continue
        green = _capture(mat, "green", has_map)
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", DEFAULT_RANGE), green, _intensity(light),
                    green, _capture(mat, "yellow", has_map)))
    return out, warnings


def _cross_len(a, b):
    cx = a[1] * b[2] - a[2] * b[1]
    cy = a[2] * b[0] - a[0] * b[2]
    cz = a[0] * b[1] - a[1] * b[0]
    return (cx * cx + cy * cy + cz * cz) ** 0.5


def _areas_lit(doc, matched, resolved, frame_for, mapped):
    out, warnings = [], []
    for light, mat, has_map, mesh, label in _lit(doc, matched, resolved, mapped)[0]:
        if _is_spot(light):
            continue
        fr = frame_for(mesh)
        if fr is None:
            warnings.append(f"{label}: no geometry for its object; skipped")
            continue
        if light.get("anchor") and light_shapes.snap_edge(fr, light["anchor"]) is None:
            warnings.append(f"{label}: no sharp edge near its snap point; using its edge chips")
        # A snapped strip (SPIKE, edge snap) is one rectangle per edge segment.
        for r in light_shapes.light_rects(light, fr):
            if _cross_len(r.half_u, r.half_v) < MIN_AREA:
                warnings.append(f"{label}: zero size; skipped")
                continue
            out.append((light, mat, has_map, r))
    return out, warnings


def areas(doc, matched, resolved, frame_for, mapped=frozenset()):
    """The strip / panel rows: (centre, half_u, half_v, range, colour,
    intensity, capture_green, capture_alert). `frame_for(mesh)` is the
    object's light_shapes.Frame, or None -- that light is skipped with a
    warning (and live_area_colours skips it too, so colours stay aligned)."""
    lit, warnings = _areas_lit(doc, matched, resolved, frame_for, mapped)
    out = []
    for light, mat, has_map, r in lit:
        green = _capture(mat, "green", has_map)
        out.append((r.centre, r.half_u, r.half_v, light.get("range", DEFAULT_RANGE),
                    green, _intensity(light), green, _capture(mat, "yellow", has_map),
                    r.joins))
    return out, warnings


def live_colours(doc, matched, resolved, fade, t, mapped=frozenset()):
    lit, _ = _lit(doc, matched, resolved, mapped)
    out = []
    for light, mat, has_map, _mesh, _label in lit:
        if not _is_spot(light):
            continue
        rgb, _k = fade.output(mat, t, has_map)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out


def live_area_colours(doc, matched, resolved, fade, t, frame_for, mapped=frozenset()):
    lit, _ = _areas_lit(doc, matched, resolved, frame_for, mapped)
    out = []
    for light, mat, has_map, _r in lit:
        rgb, _k = fade.output(mat, t, has_map)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
