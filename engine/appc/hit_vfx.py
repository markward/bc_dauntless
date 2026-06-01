"""Transient impact-VFX registry.

Per-impact descriptors are pushed via spawn(...); the renderer reads them
via snapshot() each frame. SHIELD severity is filtered here — the shield
bubble splash is handled by the renderer's shield_hit pass directly and
should not also appear as a hit_vfx descriptor.

_LIFETIME is widened from 0.5s to 0.7s to cover the CRITICAL spark burst
tail. Renderer-side fade timing is per-tier (see native/.../hit_vfx_pass.cc).

``Severity`` is re-exported here so call sites that already import from
``hit_vfx`` don't need to learn the new module name.
"""
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


_LIFETIME = 0.7  # seconds — must cover renderer's longest kTotalLife (CRITICAL = 0.65s).


_active: list[dict] = []


def spawn(position: TGPoint3, normal=None, severity=Severity.HULL) -> None:
    """Register a new hit VFX at `position`.

    `normal` is a unit TGPoint3 surface normal or None (mesh trace missed).
    `severity` is Severity.SHIELD / HULL / CRITICAL. SHIELD is a no-op —
    the shield_hit renderer pass handles its own splash.
    """
    if severity == Severity.SHIELD:
        return
    _active.append({
        "position": position,
        "normal":   normal,
        "severity": int(severity),
        "age":      0.0,
    })


def update_ages(dt: float) -> None:
    """Increment ages by dt; prune entries past _LIFETIME."""
    dt = float(dt)
    survivors = []
    for entry in _active:
        new_age = entry["age"] + dt
        if new_age < _LIFETIME:
            entry["age"] = new_age
            survivors.append(entry)
    _active.clear()
    _active.extend(survivors)


def snapshot() -> list[dict]:
    """Return a shallow copy of active VFX for renderer push."""
    return list(_active)
