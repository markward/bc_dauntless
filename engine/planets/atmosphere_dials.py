"""The "atmosphere" dev dial group (planet-atmosphere spec §7, plan deviation D4).

Tunes the nearest live planet's CATALOGUE entry live, through the shared
/ L O dial keys (engine.dev_dial_groups). Stepping edits the entry keyed by
the target's `key` -- `atmosphere.resolve_key`'s "<set>/<name>" or NIF-stem
default -- and re-pushes it to EVERY live planet sharing that key (e.g. the
two "Pink Gas Planet" instances in Albirea and Geble), not only the one the
dial happened to target, because the override lives on the catalogue entry,
not the instance.

host_loop wires `set_target_fn`/`set_push_fn` at boot (dev_mode only) to
`_nearest_live_planet` and `engine.renderer.set_instance_atmosphere`.
"""
from __future__ import annotations

import sys

DIAL_ORDER: tuple = ("thickness", "density", "limb", "color_r", "color_g", "color_b",
                     "intensity")
STEPS: dict = {
    "thickness": 0.005, "density": 0.1, "limb": 0.1,
    "color_r": 0.05, "color_g": 0.05, "color_b": 0.05,
    "intensity": 0.5,
}

# Spec ranges (atmosphere.parse_entry mirrors the low three; colour channels
# are linear [0, 1] after srgb_hex_to_linear).
_THICKNESS_MIN = 0.001  # thickness is (0, 0.25] -- strictly positive
_THICKNESS_MAX = 0.25
_DENSITY_MAX = 4.0
_LIMB_MAX = 4.0
_INTENSITY_MAX = 50.0  # shell-halo brightness multiplier only

_target_fn = lambda: None          # noqa: E731 -- () -> atmosphere.LivePlanet | None
_push_fn = lambda iid, a: None     # noqa: E731 -- (iid, Atmosphere | None) -> None


def set_target_fn(fn) -> None:
    global _target_fn
    _target_fn = fn


def set_push_fn(fn) -> None:
    global _push_fn
    _push_fn = fn


def _resolved(target):
    """`target`'s current Atmosphere (override first), or None when there is
    no target, or the target has no catalogue key (airless/unmatched)."""
    if target is None or target.key is None:
        return None
    from engine.planets import atmosphere as atmo
    return atmo.resolve(target.set_name, target.obj_name, target.nif_path)


def current() -> dict:
    a = _resolved(_target_fn())
    if a is None:
        return {}
    return {
        "thickness": a.thickness, "density": a.density, "limb": a.limb,
        "color_r": a.color[0], "color_g": a.color[1], "color_b": a.color[2],
        "intensity": a.intensity,
    }


def _clamp(name: str, v: float) -> float:
    v = round(v, 6)
    if name == "thickness":
        return min(_THICKNESS_MAX, max(_THICKNESS_MIN, v))
    if name == "density":
        return min(_DENSITY_MAX, max(0.0, v))
    if name == "limb":
        return min(_LIMB_MAX, max(0.0, v))
    if name == "intensity":
        return min(_INTENSITY_MAX, max(0.0, v))
    return min(1.0, max(0.0, v))  # colour channel, linear [0, 1]


def step(name: str, direction: int) -> None:
    target = _target_fn()
    a = _resolved(target)
    if target is None or target.key is None or a is None:
        print("[atmosphere] no atmospheric planet nearby", file=sys.stderr)
        return

    from engine.planets import atmosphere as atmo

    delta = STEPS[name] * (1 if direction > 0 else -1)
    color = list(a.color)
    thickness, density, limb, intensity = a.thickness, a.density, a.limb, a.intensity
    if name == "thickness":
        thickness = _clamp(name, thickness + delta)
    elif name == "density":
        density = _clamp(name, density + delta)
    elif name == "limb":
        limb = _clamp(name, limb + delta)
    elif name == "intensity":
        intensity = _clamp(name, intensity + delta)
    elif name == "color_r":
        color[0] = _clamp(name, color[0] + delta)
    elif name == "color_g":
        color[1] = _clamp(name, color[1] + delta)
    elif name == "color_b":
        color[2] = _clamp(name, color[2] + delta)

    new = atmo.Atmosphere(color=tuple(color), sunset_color=a.sunset_color,
                          thickness=thickness, density=density, limb=limb,
                          intensity=intensity)
    atmo.set_override(target.key, new)
    for lp in atmo.live():
        if lp.key == target.key:
            _push_fn(lp.iid, new)


def repush_live() -> None:
    """Re-push every live planet's CURRENT resolution (override first, then
    the catalogue; None for airless) through the dial group's push fn. The
    Developer Options "reload" action calls this right after
    `atmosphere.reload()`, so already-realized planets pick up catalogue
    edits and shed dial overrides -- renderer and dials agree again."""
    from engine.planets import atmosphere as atmo
    for lp in atmo.live():
        _push_fn(lp.iid, atmo.resolve(lp.set_name, lp.obj_name, lp.nif_path))


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("atmosphere", DIAL_ORDER, current, step)
