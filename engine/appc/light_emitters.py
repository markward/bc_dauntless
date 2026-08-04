"""Subsystem-attached light emitters — point / strip / cone dynamic lights.

An emitter is an independent child of a subsystem (0..N per subsystem), stored
in the ship BODY frame (same frame as glow-region positions). Persistence
mirrors glow regions: a Dauntless-invented SetLightEmitter* setter family
recorded via the property data-bag (engine/appc/properties.py) and read back
here. The runtime producer (engine/host_loop.py) transforms body->world and
feeds host_io.set_dynamic_lights; the renderer (opaque.frag) casts the light.

See docs/superpowers/specs/2026-07-29-subsystem-light-emitters-design.md.
"""
import math

from engine.appc import subsystem_glow
from engine.appc.properties import read_indexed_setter_args

_KINDS = ("point", "strip", "cone")

# Disabled-state flicker: a sputtering waveform in [0, 1], deterministic in
# game time (no Math.random) with a per-emitter phase so neighbours desync.
# Tunable like subsystem_glow.PULSE_AMP — not an authored field.
_FLICKER_FLOOR = 0.05


def default_emitter_spec(kind: str) -> dict:
    """A from-scratch emitter of `kind` with sensible default geometry.

    `radius_y`/`up` are cone-only fields (elliptical cross-section + roll)
    but are populated unconditionally — harmless for point/strip, and it
    keeps every spec dict the same shape. `radius_y == radius` (circular)
    and `up = (0,0,1)` (a canonical perpendicular to the default axis
    `(0,-1,0)`) so a from-scratch cone starts circular.
    """
    if kind not in _KINDS:
        kind = "point"
    return {
        "kind": kind,
        "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0),
        "length": 2.0,
        "radius": 1.0,
        "radius_y": 1.0,
        "up": (0.0, 0.0, 1.0),
        "color": (1.0, 0.9, 0.7),
        "intensity": 2.0,
    }


def _normalize(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-9:
        return (0.0, -1.0, 0.0)
    return (x / n, y / n, z / n)


def _derive_up(axis):
    """Canonical perpendicular-to-axis up, Gram-Schmidt off a world reference.

    Shared rule with the renderer's fallback basis (`debug_volume_pass.cc`'s
    `fallback_up`) and DebugCone: pick world-Y unless the axis is nearly
    parallel to it (then world-X), then project out the axis component and
    normalize. Used both to synthesize `up` for a legacy cone (no baked
    LightEmitterUp) and as the fallback when a spec's `up` is absent/zero.
    """
    fx, fy, fz = _normalize(axis)
    if abs(fy) < 0.99:
        ux, uy, uz = 0.0, 1.0, 0.0
    else:
        ux, uy, uz = 1.0, 0.0, 0.0
    dot = ux * fx + uy * fy + uz * fz
    ox, oy, oz = ux - dot * fx, uy - dot * fy, uz - dot * fz
    n = math.sqrt(ox * ox + oy * oy + oz * oz)
    if n < 1e-9:
        return (1.0, 0.0, 0.0)   # degenerate; shouldn't happen given the up_ref choice
    return (ox / n, oy / n, oz / n)


def _orthonormalized_up(forward, up):
    """Gram-Schmidt `up` against unit `forward`, normalized (unit, perpendicular).

    Falls back to `_derive_up(forward)` when `up` is (near-)parallel to
    `forward` (zero residual after projecting out the forward component)."""
    fx, fy, fz = forward
    ux, uy, uz = up
    dot = ux * fx + uy * fy + uz * fz
    ox, oy, oz = ux - dot * fx, uy - dot * fy, uz - dot * fz
    n = math.sqrt(ox * ox + oy * oy + oz * oz)
    if n < 1e-9:
        return _derive_up(forward)
    return (ox / n, oy / n, oz / n)


def baked_emitters(prop) -> list:
    """Read the recorded SetLightEmitter* setters back into specs, index 0..N.

    Stops at the first index whose Kind is unset (mirrors baked_glow_regions).

    `radius_y`/`up` are read the same way, but their setters
    (`SetLightEmitterRadiusY`/`SetLightEmitterUp`) are only ever emitted for
    an ELLIPTICAL cone (see `emitter_spec_to_calls`) -- a legacy or circular
    cone has neither recorded, so a missing `radius_y` defaults to the read
    `radius` (circular) and a missing `up` is derived from `axis`. This is
    what makes a save written before this feature (or a circular cone saved
    after it) load byte-identical to before.
    """
    if prop is None:
        return []
    out = []
    i = 0
    while True:
        kind = read_indexed_setter_args(prop, "LightEmitterKind", i)
        if kind is None:
            return out
        pos = read_indexed_setter_args(prop, "LightEmitterPosition", i) or (0.0, 0.0, 0.0)
        axis = read_indexed_setter_args(prop, "LightEmitterAxis", i) or (0.0, -1.0, 0.0)
        axis_t = tuple(float(c) for c in axis[:3])
        length = read_indexed_setter_args(prop, "LightEmitterLength", i)
        radius = read_indexed_setter_args(prop, "LightEmitterRadius", i)
        radius_f = float(radius[0]) if radius else 1.0
        radius_y = read_indexed_setter_args(prop, "LightEmitterRadiusY", i)
        up = read_indexed_setter_args(prop, "LightEmitterUp", i)
        color = read_indexed_setter_args(prop, "LightEmitterColor", i) or (1.0, 0.9, 0.7)
        intensity = read_indexed_setter_args(prop, "LightEmitterIntensity", i)
        out.append({
            "kind": str(kind[0]),
            "position": tuple(float(c) for c in pos[:3]),
            "axis": axis_t,
            "length": float(length[0]) if length else 0.0,
            "radius": radius_f,
            "radius_y": float(radius_y[0]) if radius_y else radius_f,
            "up": tuple(float(c) for c in up[:3]) if up else _derive_up(axis_t),
            "color": tuple(float(c) for c in color[:3]),
            "intensity": float(intensity[0]) if intensity else 1.0,
        })
        i += 1


def emitter_spec_to_struct(spec: dict) -> dict:
    """Convert a BODY-frame emitter spec to set_dynamic_lights dict keys.

    Positions/axis/up stay body-frame here; the host-loop producer transforms
    them to world (up is a direction: rotation-only, like direction). Point
    => degenerate segment (no position_b, no cone). Strip => two endpoints.
    Cone => apex + direction + up + two spot tangents (`spot_tan_x` =
    radius/length, `spot_tan_y` = radius_y/length -- NOT cosines; Task 1's
    renderer consumes tangents directly for the elliptical cone).
    """
    kind = spec.get("kind", "point")
    px, py, pz = spec["position"]
    d = {
        "position": (px, py, pz),
        "color": tuple(spec["color"]),
        "radius": float(spec["radius"]),
        "intensity": float(spec["intensity"]),
    }
    if kind == "point":
        return d
    ax, ay, az = _normalize(spec["axis"])
    length = float(spec["length"])
    if kind == "strip":
        half = length / 2.0
        d["position"] = (px - ax * half, py - ay * half, pz - az * half)
        d["position_b"] = (px + ax * half, py + ay * half, pz + az * half)
        return d
    # cone
    length_safe = max(length, 1e-6)
    up = spec.get("up") or _derive_up((ax, ay, az))
    d["direction"] = (ax, ay, az)
    d["up"] = _orthonormalized_up((ax, ay, az), up)
    d["spot_tan_x"] = float(spec["radius"]) / length_safe
    d["spot_tan_y"] = float(spec.get("radius_y", spec["radius"])) / length_safe
    return d


def emitter_flicker(now: float, phase: float) -> float:
    """Sputtering waveform, deterministic in game time.

    Two desynced sine waves are multiplied together and clamped to positive,
    which biases the intermediate `v` into [0.35, 1.0] (it never reaches 0),
    then `_FLICKER_FLOOR` is applied as an ADDITIVE floor on top of that
    normalized-to-[0,1] value: `_FLICKER_FLOOR + (1 - _FLICKER_FLOOR) * v`.
    Because `v` bottoms out at 0.35 rather than 0, the actual output range is
    approximately [0.38, 1.0] — `_FLICKER_FLOOR` is never the effective
    minimum, it just nudges the whole curve up slightly. Net effect: a
    disabled emitter dims and stutters rather than snapping fully dark.
    `phase` is per-emitter so neighbouring disabled emitters don't flicker in
    lockstep.
    """
    a = math.sin(now * 37.0 + phase)
    b = math.sin(now * 11.3 + phase * 2.0)
    v = 0.35 + 0.65 * max(0.0, a * b)
    return _FLICKER_FLOOR + (1.0 - _FLICKER_FLOOR) * max(0.0, min(1.0, v))


def resolve_emitter_intensity(spec, sub, now, throttle_frac=0.0,
                              is_impulse=False, powered=True, phase=0.0):
    """Per-frame emitter intensity scalar, or None when fully off.

    HEALTHY -> base intensity; DISABLED -> base * flicker(now); DESTROYED -> off.
    Impulse-parented emitters additionally scale by subsystem_glow.impulse_gain
    so they brighten with commanded throttle exactly like the impulse glow —
    but only while the subsystem is HEALTHY, mirroring ShipGlowController
    (a disabled impulse pod gets flicker only, no throttle brightening).
    """
    base = float(spec["intensity"])
    state = subsystem_glow.glow_state(sub)
    if state == subsystem_glow.DESTROYED:
        return None
    out = base
    if state == subsystem_glow.DISABLED:
        out = base * emitter_flicker(now, phase)
    if is_impulse:
        out *= subsystem_glow.impulse_gain(
            throttle_frac, now, powered and (state == subsystem_glow.HEALTHY))
    if out <= 0.0:
        return None
    return out
