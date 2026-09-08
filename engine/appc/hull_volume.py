"""Push BC's authored damage-volume resolution to the hull-volume baker.

`ShipProperty.SetDamageResolution` is authored per ship in every hardpoint file
-- Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15 -- and copied onto the
ship by `ShipClass` property application. Until now nothing read it.

It is the cell size, in MODEL UNITS, that the ship's damage volume should be
baked at: a per-ship detail ratio which a global quality multiplier then scales.
It is also finer than what BC itself shipped (Galaxy 10 vs a baked 15, Akira 8
vs 15, Warbird 12 vs 25) -- and the Warbird, the worst mismatch in the fleet, is
exactly the ship whose breaches were seen cutting into nothing.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md
"""
from engine import renderer as _renderer

__all__ = ["push_resolution"]


def push_resolution(ship, iid) -> bool:
    """Send `ship`'s authored resolution for instance `iid`.

    Returns True only when a positive resolution was actually pushed. A ship
    that never had one keeps the native default rather than being handed 0.0,
    which the baker would divide by.

    Never raises: a ship must spawn even if this VFX detail cannot be recorded.
    """
    getter = getattr(ship, "GetDamageResolution", None)
    if getter is None:
        return False
    try:
        resolution = float(getter())
    except (TypeError, ValueError):
        return False
    if not resolution > 0.0:
        return False
    try:
        _renderer.hull_volume_set_resolution(iid, resolution)
    except Exception:
        return False
    return True
