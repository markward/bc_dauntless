"""Transient impact-VFX registry.

Per-impact descriptors are pushed via spawn(...); the renderer reads them
via snapshot() each frame. SHIELD severity is filtered here — the shield
bubble splash is handled by the renderer's shield_hit pass directly and
should not also appear as a hit_vfx descriptor.

Descriptor lifetime is per-descriptor: flash-only hits prune at
_FLASH_LIFETIME, while spark-bearing hits live to _SPARK_LIFETIME so they
cover the renderer's longer kSparkLife. Renderer-side fade/size timing is
per-tier and per-sprite (see native/.../hit_vfx_pass.cc).

``Severity`` is re-exported here so call sites that already import from
``hit_vfx`` don't need to learn the new module name.
"""
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


# Per-descriptor lifetimes. Flash-only hits (every phaser tick lands one) prune
# quickly so sustained fire doesn't pile up no-op descriptors; descriptors that
# carry a spark burst live long enough for the renderer's kSparkLife (5.0s).
_FLASH_LIFETIME = 0.7  # seconds — covers the renderer flash fade (tier total_life ≤ 0.65s)
_SPARK_LIFETIME = 3.2  # seconds — covers the renderer spark life (kSparkLife = 3.0s)


def _entry_lifetime(entry) -> float:
    return _SPARK_LIFETIME if entry.get("spark_count", 0) > 0 else _FLASH_LIFETIME


_active: list[dict] = []


def spawn(position: TGPoint3, normal=None, severity=Severity.HULL,
          *, instance_id=None, body_point=None, body_normal=None,
          weapon_kind=1, spark_count=0) -> None:
    """Register a new hit VFX at `position` (world space).

    `normal` is a unit TGPoint3 surface normal or None (mesh trace missed).
    `severity` is Severity.SHIELD / HULL / CRITICAL. SHIELD is a no-op —
    the shield_hit renderer pass handles its own splash.

    Spark fields (all optional; spark_count == 0 disables the burst):
      instance_id  — receiving ship's renderer instance id (hull anchor)
      body_point   — impact point in ship body frame (model units, 3-tuple)
      body_normal  — surface normal in ship body frame (3-tuple)
      weapon_kind  — SPARK_KIND_PHASER (0) / SPARK_KIND_TORPEDO (1) tint+cone
      spark_count  — number of sparks to emit
    """
    if severity == Severity.SHIELD:
        return
    _active.append({
        "position":    position,
        "normal":      normal,
        "severity":    int(severity),
        "age":         0.0,
        "instance_id": instance_id,
        "body_point":  body_point,
        "body_normal": body_normal,
        "weapon_kind": int(weapon_kind),
        "spark_count": int(spark_count),
    })


def update_ages(dt: float) -> None:
    """Increment ages by dt; prune entries past their per-descriptor lifetime
    (spark-bearing entries live longer — see _entry_lifetime)."""
    dt = float(dt)
    survivors = []
    for entry in _active:
        new_age = entry["age"] + dt
        if new_age < _entry_lifetime(entry):
            entry["age"] = new_age
            survivors.append(entry)
    _active.clear()
    _active.extend(survivors)


def snapshot() -> list[dict]:
    """Return a shallow copy of active VFX for renderer push."""
    return list(_active)
