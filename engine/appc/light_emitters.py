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

from engine.appc.properties import read_indexed_setter_args

_KINDS = ("point", "strip", "cone")


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
