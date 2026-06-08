"""Ship Property Viewer — logic core (camera, projection, descriptors, picking).

Pure Python: no GL or CEF imports. See
docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from engine.appc.math import TGPoint3, TGMatrix3


def subsystem_world_position(sub) -> TGPoint3:
    """World mount point of a subsystem: ship location + body->world rotated
    local mount. No scale factor (BC stores mounts in world units relative to
    the ship centre — see engine/appc/subsystems.py:769). Returns the ship
    location if the subsystem has no 3D mount."""
    ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return TGPoint3(0.0, 0.0, 0.0)
    ship_pos = ship.GetWorldLocation()
    local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    if not isinstance(local, TGPoint3):
        return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
    offset = TGPoint3(local.x, local.y, local.z)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)  # R . offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)
