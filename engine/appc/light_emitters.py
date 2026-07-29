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
    """A from-scratch emitter of `kind` with sensible default geometry."""
    if kind not in _KINDS:
        kind = "point"
    return {
        "kind": kind,
        "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0),
        "length": 2.0,
        "radius": 1.0,
        "color": (1.0, 0.9, 0.7),
        "intensity": 2.0,
    }


def _normalize(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-9:
        return (0.0, -1.0, 0.0)
    return (x / n, y / n, z / n)


def baked_emitters(prop) -> list:
    """Read the recorded SetLightEmitter* setters back into specs, index 0..N.

    Stops at the first index whose Kind is unset (mirrors baked_glow_regions).
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
        length = read_indexed_setter_args(prop, "LightEmitterLength", i)
        radius = read_indexed_setter_args(prop, "LightEmitterRadius", i)
        color = read_indexed_setter_args(prop, "LightEmitterColor", i) or (1.0, 0.9, 0.7)
        intensity = read_indexed_setter_args(prop, "LightEmitterIntensity", i)
        out.append({
            "kind": str(kind[0]),
            "position": tuple(float(c) for c in pos[:3]),
            "axis": tuple(float(c) for c in axis[:3]),
            "length": float(length[0]) if length else 0.0,
            "radius": float(radius[0]) if radius else 1.0,
            "color": tuple(float(c) for c in color[:3]),
            "intensity": float(intensity[0]) if intensity else 1.0,
        })
        i += 1


def emitter_spec_to_struct(spec: dict) -> dict:
    """Convert a BODY-frame emitter spec to set_dynamic_lights dict keys.

    Positions/axis stay body-frame here; the host-loop producer transforms them
    to world. Point => degenerate segment (no position_b, no cone). Strip =>
    two endpoints. Cone => apex + direction + derived cos(half-angle).
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
    d["direction"] = (ax, ay, az)
    d["cos_half_angle"] = math.cos(math.atan2(float(spec["radius"]), max(length, 1e-6)))
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
