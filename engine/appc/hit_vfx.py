"""Transient impact-VFX registry.  Tiny — just a list of (position, age)
pairs with a 0.5s lifetime.  Host_loop's per-frame combat advance calls
spawn() on each torpedo impact and pushes snapshot() to the renderer.
"""
from engine.appc.math import TGPoint3


_LIFETIME = 0.5  # seconds


# Internal storage: list of dicts with "position" and "age" keys.
# Dict shape matches what the renderer binding expects.
_active: list[dict] = []


def spawn(position: TGPoint3) -> None:
    """Register a new hit VFX at `position` with age 0."""
    _active.append({"position": position, "age": 0.0})


def update_ages(dt: float) -> None:
    """Increment ages by dt; prune expired (>= _LIFETIME)."""
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
