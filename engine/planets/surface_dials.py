"""The "surface" dev dial group (planet-surface-detail spec §7).

Mirrors `engine.planets.atmosphere_dials`, but splits across TWO
independent targets instead of one:

- `strength`, `albedo`, `scale`, `ocean_tolerance` edit the nearest live
  SURFACE planet's CATALOGUE entry (like the atmosphere dials: the override
  lives on the key, not the instance, and re-pushes to every live planet
  sharing that key).
- `bump`, `roughness`, `coast_k`, `gas_rate_gups`, `gas_period_s` edit the
  planet surface-detail clipmap's current TARGET TYPE's native type-table
  entry (`engine.renderer.set_surface_type_params`) -- a per-surface-type
  table, not per-planet. Shape fields (base_wavelength_gu, max_octaves,
  gain, amplitude, crack_width, stretch, warp) are not dialled here; `ridged`
  is hard-coded per type and never exposed as a dial either.
- `budget` sets the clipmap's per-frame bake cost budget
  (`engine.renderer.set_planet_detail_budget`); it has no planet target at
  all, so it steps ×/÷ 2 and is tracked locally (there is no native getter).

host_loop wires `set_target_fn`/`set_push_fn` (nearest live surface planet,
by surface distance, mirroring `_nearest_live_planet`) and
`set_target_type_fn`/`set_type_params_fns`/`set_budget_fn` (the native
bindings via engine.renderer) at boot, dev_mode only.
"""
from __future__ import annotations

import dataclasses
import sys

DIAL_ORDER: tuple = ("strength", "albedo", "scale", "bump", "roughness", "coast_k",
                     "ocean_tolerance", "gas_rate_gups", "gas_period_s", "budget")
STEPS: dict = {
    "strength": 0.05, "albedo": 0.05, "scale": 0.05, "bump": 0.05,
    "roughness": 0.02, "coast_k": 0.01, "ocean_tolerance": 0.01,
    "gas_rate_gups": 0.05, "gas_period_s": 5.0,
}

_CATALOGUE_FIELDS = frozenset({"strength", "albedo", "scale", "ocean_tolerance"})
_TYPE_FIELDS = frozenset({"bump", "roughness", "coast_k", "gas_rate_gups", "gas_period_s"})

# Ranges. strength/albedo/scale/ocean_tolerance mirror
# engine.planets.surface.parse_surface's own spec-§7 ranges; the type-table
# fields have no catalogue spec, so these are permissive dev-tuning bounds.
_STRENGTH_MAX = 4.0
_ALBEDO_MAX = 4.0
_SCALE_MIN, _SCALE_MAX = 0.25, 4.0
_OCEAN_TOLERANCE_MIN, _OCEAN_TOLERANCE_MAX = 0.001, 1.0
_BUMP_MAX = 4.0
# Floor matches opaque.frag's `clamp(rough, 0.02, 1.0)` (fix round 1, M4):
# below 0.02 the shader clamps it anyway, so a lower dial floor would be a
# silent no-op past that point.
_ROUGHNESS_MIN, _ROUGHNESS_MAX = 0.02, 1.0
_COAST_K_MAX = 1.0
_GAS_RATE_MAX = 10.0
_GAS_PERIOD_MIN, _GAS_PERIOD_MAX = 1.0, 600.0
_BUDGET_MIN, _BUDGET_MAX = 1024, 1 << 24

_target_fn = lambda: None              # noqa: E731 -- () -> surface.LiveSurface | None
_push_fn = lambda iid, s: None         # noqa: E731 -- (iid, Surface | None) -> None
_target_type_fn = lambda: 0            # noqa: E731 -- () -> int (0 = no clipmap target)
_get_type_params_fn = lambda t: {}     # noqa: E731 -- (int) -> dict
_set_type_params_fn = lambda t, p: None  # noqa: E731 -- (int, dict) -> None
_set_budget_fn = lambda cost: None     # noqa: E731 -- (int) -> None

_budget = 65536 * 8   # PlanetDetailPass::kDefaultBudget (spec default)


def set_target_fn(fn) -> None:
    global _target_fn
    _target_fn = fn


def set_push_fn(fn) -> None:
    global _push_fn
    _push_fn = fn


def set_target_type_fn(fn) -> None:
    global _target_type_fn
    _target_type_fn = fn


def set_type_params_fns(get_fn, set_fn) -> None:
    global _get_type_params_fn, _set_type_params_fn
    _get_type_params_fn = get_fn
    _set_type_params_fn = set_fn


def set_budget_fn(fn) -> None:
    global _set_budget_fn
    _set_budget_fn = fn


def _resolved(target):
    """`target`'s current Surface (override first), or None with no target
    or an unresolved/no-detail target."""
    if target is None:
        return None
    from engine.planets import surface as surf
    return surf.resolve_surface(target.set_name, target.obj_name, target.nif_path)


def _target_key(target):
    if target is None:
        return None
    from engine.planets import surface as surf
    return surf.resolve_surface_key(target.set_name, target.obj_name, target.nif_path)


def current() -> dict:
    out: dict = {}
    target = _target_fn()
    s = _resolved(target)
    if s is not None:
        out["strength"] = s.strength
        out["albedo"] = s.albedo
        out["scale"] = s.scale
        out["ocean_tolerance"] = s.ocean_tolerance
    t = _target_type_fn()
    if t:
        p = _get_type_params_fn(t)
        out["bump"] = p["bump"]
        out["roughness"] = p["roughness"]
        out["coast_k"] = p["coast_k"]
        out["gas_rate_gups"] = p["gas_rate_gups"]
        out["gas_period_s"] = p["gas_period_s"]
    if s is not None or t:
        out["budget"] = _budget
    return out


def _clamp(name: str, v: float) -> float:
    v = round(v, 6)
    if name == "strength":
        return min(_STRENGTH_MAX, max(0.0, v))
    if name == "albedo":
        return min(_ALBEDO_MAX, max(0.0, v))
    if name == "scale":
        return min(_SCALE_MAX, max(_SCALE_MIN, v))
    if name == "ocean_tolerance":
        return min(_OCEAN_TOLERANCE_MAX, max(_OCEAN_TOLERANCE_MIN, v))
    if name == "bump":
        return min(_BUMP_MAX, max(0.0, v))
    if name == "roughness":
        return min(_ROUGHNESS_MAX, max(_ROUGHNESS_MIN, v))
    if name == "coast_k":
        return min(_COAST_K_MAX, max(0.0, v))
    if name == "gas_rate_gups":
        return min(_GAS_RATE_MAX, max(0.0, v))
    if name == "gas_period_s":
        return min(_GAS_PERIOD_MAX, max(_GAS_PERIOD_MIN, v))
    return v


def _step_catalogue(name: str, direction: int) -> None:
    target = _target_fn()
    s = _resolved(target)
    if target is None or s is None:
        print("[surface] no surface planet nearby", file=sys.stderr)
        return

    from engine.planets import surface as surf

    key = _target_key(target)
    delta = STEPS[name] * (1 if direction > 0 else -1)
    strength, albedo, scale, ocean_tolerance = (
        s.strength, s.albedo, s.scale, s.ocean_tolerance)
    if name == "strength":
        strength = _clamp(name, strength + delta)
    elif name == "albedo":
        albedo = _clamp(name, albedo + delta)
    elif name == "scale":
        scale = _clamp(name, scale + delta)
    elif name == "ocean_tolerance":
        ocean_tolerance = _clamp(name, ocean_tolerance + delta)

    new = dataclasses.replace(s, strength=strength, albedo=albedo, scale=scale,
                              ocean_tolerance=ocean_tolerance)
    surf.set_override(key, new)
    for lp in surf.live():
        if surf.resolve_surface_key(lp.set_name, lp.obj_name, lp.nif_path) == key:
            _push_fn(lp.iid, new)


def _step_type_table(name: str, direction: int) -> None:
    t = _target_type_fn()
    if not t:
        print("[surface] no planet surface-detail target", file=sys.stderr)
        return
    params = _get_type_params_fn(t)
    delta = STEPS[name] * (1 if direction > 0 else -1)
    new_v = _clamp(name, params[name] + delta)
    _set_type_params_fn(t, {name: new_v})


def _step_budget(direction: int) -> None:
    global _budget
    v = _budget * 2 if direction > 0 else _budget / 2
    _budget = int(min(_BUDGET_MAX, max(_BUDGET_MIN, round(v))))
    _set_budget_fn(_budget)


def step(name: str, direction: int) -> None:
    if name == "budget":
        _step_budget(direction)
        return
    if name in _CATALOGUE_FIELDS:
        _step_catalogue(name, direction)
        return
    if name in _TYPE_FIELDS:
        _step_type_table(name, direction)
        return
    raise ValueError("unknown surface dial: %r" % (name,))


def repush_live() -> None:
    """Re-push every live surface planet's CURRENT resolution (override
    first, then the catalogue; None for no detail) -- the Developer Options
    "Reload Planet Surfaces" action calls this right after
    `engine.planets.atmosphere.reload()` (the shared catalogue file memo)
    and `engine.planets.surface.reload()` (drops this group's overrides)."""
    from engine.planets import surface as surf
    for lp in surf.live():
        _push_fn(lp.iid, surf.resolve_surface(lp.set_name, lp.obj_name, lp.nif_path))


def label():
    """Whose entries the dials edit right now: the catalogue target's
    "<obj_name> (<set_name>) [<key>]" and/or the clipmap's "type=<N>", or
    None with neither target. Mirrors atmosphere_dials.label."""
    parts = []
    target = _target_fn()
    key = _target_key(target)
    if target is not None and key is not None and _resolved(target) is not None:
        parts.append("%s (%s) [%s]" % (target.obj_name, target.set_name, key))
    t = _target_type_fn()
    if t:
        parts.append("type=%d" % t)
    return " ".join(parts) if parts else None


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("surface", DIAL_ORDER, current, step, label=label)
