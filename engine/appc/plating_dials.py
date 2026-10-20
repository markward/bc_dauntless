"""SPIKE (damage redesign): hull-plating layer look dials.

Torpedo scorch records carry a running hit total (`wear`); the hull shader
(opaque.frag apply_plating) strips plating PANELS where wear crosses
`strip_wear`, exposing procedural ribs (frames along body Y + stringers) over
a dark inner skin, and breaks the ribs past `rib_break_wear`. Depth is faked
by a short parallax march, so nothing is cut in the mesh.

Lengths are MODEL units (~1.75 m: 1 GU = 175 m ~ 101 model units). Real
ribs (~1 m) are a pixel at combat range, so the defaults are exaggerated
for readability. Tuned live with the shared
/ L O keys once Developer Options -> "Dial keys" selects "plating"
(engine/dev_dial_groups.py). Not persisted. DEFAULTS MUST match
frame.cc's dauntless_plating::g_params (slot order = DIAL_ORDER).
"""
DEFAULTS: dict = {
    "enabled": 1.0,
    "panel_size": 6.0,
    "frame_spacing": 8.0,
    "stringer_spacing": 5.0,
    "rib_width": 1.2,
    "plate_depth": 0.6,
    "rib_depth": 1.2,
    "reach": 0.40,           # x scorch decal radius (photon: ~51 m radius)
    "strip_wear": 0.5,
    "rib_break_wear": 2.5,
    "buckle_band": 0.35,
    "edge_noise": 0.6,
    "debug": 0.0,            # 1 = stripped panels magenta, buckled yellow
    "soot": 0.3,             # x the scorch deposit while plating is on
    "metal_brightness": 1.0,
}
DIAL_ORDER: tuple = tuple(DEFAULTS)
_STEP = {
    "enabled": 1.0, "panel_size": 0.5, "frame_spacing": 0.5,
    "stringer_spacing": 0.5, "rib_width": 0.2, "plate_depth": 0.1,
    "rib_depth": 0.1, "reach": 0.05, "strip_wear": 0.1,
    "rib_break_wear": 0.25, "buckle_band": 0.05, "edge_noise": 0.1,
    "debug": 1.0, "soot": 0.1, "metal_brightness": 0.1,
}
_MIN = {k: 0.0 for k in DEFAULTS}
_MIN.update({"panel_size": 0.25, "frame_spacing": 0.25,
             "stringer_spacing": 0.25, "rib_width": 0.02})
_MAX = {"enabled": 1.0, "debug": 1.0}

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
