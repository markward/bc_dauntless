"""SPIKE (damage redesign): hull-plating layer look dials.

Torpedo scorch records carry a running hit total (`wear`); the hull shader
(opaque.frag apply_plating) strips plating PANELS where wear crosses
`strip_wear`, exposing the hull's skeleton over a dark inner skin, and breaks
it past `rib_break_wear`. The skeleton follows the detected structure parts
(voxel::detect_structure_parts): saucer = spokes (primary, branching outward)
+ rings (secondary); nacelle / hull = hoops (primary) + stringers
(secondary); box = frames along its long axis + stringers. Panels are
skeleton cells, subdivided to ~panel_size. Depth is a short march along the
view ray, so nothing is cut in the mesh.

Lengths are MODEL units (~1.75 m: 1 GU = 175 m ~ 101 model units). Real
ribs (~1 m) are a pixel at combat range, so the defaults are exaggerated
for readability. Tuned live with the shared
/ L O keys once Developer Options -> "Dial keys" selects "plating"
(engine/dev_dial_groups.py), and in coarse presets from Developer Options ->
"Hull damage" (engine/dev_hull_damage_tuning.py), which writes through
`set_value` here so the two stay in sync. Not persisted.

The defaults' one source is frame.cc's dauntless_plating::g_params
initializer (slot order = DIAL_ORDER), reported by the binding
`plating_param_defaults()`; `register` prefers it. DEFAULTS is the headless
fallback, pinned equal by tests/host/test_plating_defaults_drift.py.
"""
import struct
from typing import Optional

DEFAULTS: dict = {
    "enabled": 1.0,
    "panel_size": 6.0,
    "primary_spacing": 8.0,
    "secondary_spacing": 5.0,
    "member_width": 1.2,
    "plate_depth": 0.6,
    "rib_depth": 1.2,
    "reach": 0.40,           # x scorch decal radius (photon: ~51 m radius)
    "strip_wear": 0.5,
    "rib_break_wear": 2.5,
    "buckle_band": 0.35,
    "edge_noise": 0.6,
    "debug": 0.0,            # 1 = stripped magenta / buckled yellow / edge cyan, 2 = colour by part
    "soot": 0.75,            # x the scorch deposit while plating is on
    "metal_brightness": 1.0,
    "member_bend": 1.5,      # model units of member distortion at full damage
    "breach_wear": 4.5,      # wear at which the inner pressure hull tears open
    "inner_brightness": 1.0,
    "tear_mix": 0.6,         # 0 = whole panels, 1 = torn freely across them
    "tear_noise": 0.9,       # jaggedness of the torn edge (wear units)
    "peel_band": 0.35,       # plate this far short of tearing curls up
    "member_survive": 4.0,   # wear past breach a primary member still spans the hole
    "toughness_spread": 0.6,  # per-panel breach wear varies by up to 0.4 x this (fraction)
    "breach_lumps": 1.0,     # wear units of hole-scale breach-threshold variation
    "deck_break_wear": 6.0,  # (interior pass) wear at which decks break
    "interior": 1.0,         # (interior pass) 1 = interior behind holes
    "force_program": 0.0,    # DEBUG/perf: 1 = undamaged hulls draw through the plating program
    "lod_footprint": 1.0,    # perf: short path where pixel footprint > this x member_width; <= 0 off
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {
    "enabled": 1.0, "panel_size": 0.5, "primary_spacing": 0.5,
    "secondary_spacing": 0.5, "member_width": 0.2, "plate_depth": 0.1,
    "rib_depth": 0.1, "reach": 0.05, "strip_wear": 0.1,
    "rib_break_wear": 0.25, "buckle_band": 0.05, "edge_noise": 0.1,
    "debug": 1.0, "soot": 0.1, "metal_brightness": 0.1,
    "member_bend": 0.25, "breach_wear": 0.25, "inner_brightness": 0.1,
    "tear_mix": 0.1, "tear_noise": 0.1, "peel_band": 0.05,
    "member_survive": 0.25, "toughness_spread": 0.1, "breach_lumps": 0.25,
    "deck_break_wear": 0.25, "interior": 1.0,
    "force_program": 1.0, "lod_footprint": 0.25,
}
_MIN = {k: 0.0 for k in DEFAULTS}
_MIN.update({"panel_size": 0.25, "primary_spacing": 0.25,
             "secondary_spacing": 0.25, "member_width": 0.02})
_MAX = {"enabled": 1.0, "debug": 2.0, "tear_mix": 1.0, "interior": 1.0,
         "force_program": 1.0}

# The defaults in force: DEFAULTS until `register` reads the native ones.
_defaults: dict = dict(DEFAULTS)
_dials: dict = dict(DEFAULTS)


def _f32_shortest(v: float) -> float:
    """The shortest decimal that round-trips float32 `v` (0.4f -> 0.4), so
    native defaults compare equal to the Python literals they mirror."""
    packed = struct.pack("<f", v)
    for digits in range(6, 10):
        cand = float("%.*g" % (digits, v))
        if struct.pack("<f", cand) == packed:
            return cand
    return float(v)


def native_defaults() -> Optional[dict]:
    """The C++ defaults keyed by DIAL_ORDER, or None when the binding (or
    the renderer) is unavailable -- headless, or a stale module."""
    try:
        from engine import renderer
        native = list(renderer.plating_param_defaults())
    except Exception:
        return None
    if len(native) < len(DIAL_ORDER):
        return None
    return {k: _f32_shortest(float(native[i])) for i, k in enumerate(DIAL_ORDER)}


def defaults() -> dict:
    return dict(_defaults)


def reset() -> None:
    global _dials
    _dials = dict(_defaults)


def reset_state() -> None:
    """Back to import state (DEFAULTS, no native defaults), with NO push:
    tests/conftest.py's autouse reset, headless-safe."""
    global _defaults, _dials
    _defaults = dict(DEFAULTS)
    _dials = dict(DEFAULTS)


def current() -> dict:
    return dict(_dials)


def params() -> list:
    return [_dials[k] for k in DIAL_ORDER]


def push() -> None:
    try:
        from engine import renderer
        renderer.set_plating_params(params())
    except Exception as _e:
        import engine.dev_mode as dev_mode
        dev_mode.log_swallowed("plating params push", _e)


def _clamp(name: str, v: float) -> float:
    v = max(_MIN[name], round(float(v), 4))
    if name in _MAX:
        v = min(_MAX[name], v)
    return v


def _step(name: str, direction: int) -> None:
    _dials[name] = _clamp(name, _dials[name] + (
        _STEP[name] if direction > 0 else -_STEP[name]))
    push()


def set_value(name: str, value: float) -> None:
    """Set one dial (clamped like a dial step) and push: the Developer
    Options rows write through here, the same path as / L O."""
    _dials[name] = _clamp(name, value)
    push()


def set_values(values: dict) -> None:
    """Several dials, one push."""
    for name, value in values.items():
        _dials[name] = _clamp(name, value)
    push()


def register() -> None:
    """Dev boot. Prefers the native defaults (DEFAULTS when the binding is
    absent). DAUNTLESS_PLATING=0 starts with the layer off (perf A/B);
    DAUNTLESS_PLATING_LOD=<x> sets lod_footprint (0 = full detail
    everywhere, the pixel-footprint LOD's A/B)."""
    import os
    from engine import dev_dial_groups
    global _defaults, _dials
    native = native_defaults()
    if native is not None:
        _defaults = native
        _dials = dict(native)
    if os.environ.get("DAUNTLESS_PLATING", "1").strip() == "0":
        _dials["enabled"] = 0.0
    if os.environ.get("DAUNTLESS_PLATING_FORCE_PROGRAM", "0").strip() == "1":
        _dials["force_program"] = 1.0
    lod = os.environ.get("DAUNTLESS_PLATING_LOD", "").strip()
    if lod:
        try:
            _dials["lod_footprint"] = _clamp("lod_footprint", float(lod))
        except ValueError:
            pass
    dev_dial_groups.register_group("plating", DIAL_ORDER, current, _step)
    push()
