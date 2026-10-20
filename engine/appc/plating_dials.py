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
(engine/dev_dial_groups.py). Not persisted. DEFAULTS MUST match
frame.cc's dauntless_plating::g_params[24] (slot order = DIAL_ORDER).
"""
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
    "member_survive": 0.25,
}
_MIN = {k: 0.0 for k in DEFAULTS}
_MIN.update({"panel_size": 0.25, "primary_spacing": 0.25,
             "secondary_spacing": 0.25, "member_width": 0.02})
_MAX = {"enabled": 1.0, "debug": 2.0, "tear_mix": 1.0}

_dials: dict = dict(DEFAULTS)


def reset() -> None:
    global _dials
    _dials = dict(DEFAULTS)


def current() -> dict:
    return dict(_dials)


def params() -> list:
    return [_dials[k] for k in DIAL_ORDER]


def push() -> None:
    try:
        from engine import renderer
        renderer.set_plating_params(params())
    except Exception:
        pass


def _step(name: str, direction: int) -> None:
    v = _dials[name] + (_STEP[name] if direction > 0 else -_STEP[name])
    v = max(_MIN[name], round(v, 4))
    if name in _MAX:
        v = min(_MAX[name], v)
    _dials[name] = v
    push()


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("plating", DIAL_ORDER, current, _step)
    push()
