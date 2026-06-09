"""Runtime mount marker for an ObjectEmitterProperty (shuttle / probe / decoy
launch point). Not a ShipSubsystem: no condition, not targetable, not
damageable. Surfaced by the Ship Property Viewer as an informational mount
pin; excluded from the target list and damage panel.

See docs/superpowers/specs/2026-06-09-faithful-hardpoint-subsystem-loading-design.md
"""
from __future__ import annotations

from engine.appc.math import TGPoint3


class ObjectEmitter:
    def __init__(self, prop=None):
        self._property = prop
        self._name = prop.GetName() if (prop is not None and hasattr(prop, "GetName")) else ""
        self._position = TGPoint3(0.0, 0.0, 0.0)
        self._emitted_type = 0
        self._parent_ship = None
        if prop is not None:
            p = prop.GetPosition() if hasattr(prop, "GetPosition") else None
            if isinstance(p, TGPoint3):
                self._position = TGPoint3(p.x, p.y, p.z)
            if hasattr(prop, "GetEmittedObjectType"):
                t = prop.GetEmittedObjectType()
                if isinstance(t, int):
                    self._emitted_type = t

    def GetName(self) -> str:
        return self._name

    def GetProperty(self):
        return self._property

    def GetPosition(self) -> TGPoint3:
        # Local mount in body frame; the viewer rotates it into world space.
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetEmittedObjectType(self) -> int:
        return self._emitted_type

    def GetParentShip(self):
        return self._parent_ship

    def SetParentShip(self, ship) -> None:
        self._parent_ship = ship
