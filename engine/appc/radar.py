"""SDK radar shim — RadarDisplay / RadarScope / RadarBlip.

Mirrors the surface SDK scripts touch in
sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:471-476 and
sdk/Build/scripts/Tactical/Interface/RadarDisplay.py + RadarScope.py.
No rendering — the SensorsPanel view layer does that. Shim's only
job is to let bridge-load scripts run without raising.
"""
from __future__ import annotations
from typing import List, Optional


class _RadarBlip:
    """SDK App.py:8535 — extends TGIcon. SDK calls: SetShipID, GetShipID,
    plus the inherited TGIcon mutators we don't need yet."""

    def __init__(self, group_name: str = "", index: int = 0):
        self._group = str(group_name)
        self._index = int(index)
        self._ship_id: int = 0

    def SetShipID(self, ship_id) -> None:
        self._ship_id = int(ship_id)

    def GetShipID(self) -> int:
        return self._ship_id


class _RadarScope:
    """SDK App.py:8554 — extends TGPane. RadarScope.py builds a 7-slot
    child layout (ship icon, ring, bracket pane, target bracket, blip
    pane, phaser pane, background pane). The shim doesn't enforce slot
    semantics — it just accepts AddChild calls and stores them."""

    # Child-slot constants the SDK reads (RadarScope.py uses App.RadarScope.SHIP_ICON etc.)
    SHIP_ICON       = 0
    RADAR_RING      = 1
    BRACKET_PANE    = 2
    TARGET_BRACKET  = 3
    BLIP_PANE       = 4
    PHASER_LINE_PANE = 5
    BACKGROUND_PANE  = 6

    def __init__(self, w: float = 0.0, h: float = 0.0):
        self._w = float(w)
        self._h = float(h)
        self._children: List[object] = []
        self._target_bracket: Optional[_RadarBlip] = None

    # TGPane surface (the bits RadarScope.py touches).
    def SetNoFocus(self) -> None: pass
    def Layout(self) -> None: pass
    def GetWidth(self) -> float:  return self._w
    def GetHeight(self) -> float: return self._h

    def Resize(self, w: float, h: float, _flags: int = 0) -> None:
        self._w = float(w)
        self._h = float(h)

    def AddChild(self, child, _x: float = 0.0, _y: float = 0.0, _z: int = 0) -> None:
        self._children.append(child)

    def GetNthChild(self, n: int):
        if 0 <= n < len(self._children):
            return self._children[n]
        return None

    def GetNumChildren(self) -> int:
        return len(self._children)

    # RadarScope-specific.
    def CreateShipIcon(self):
        """SDK returns a TGIcon. The shim returns a generic placeholder
        object the SDK then re-adds via AddChild."""
        return _RadarBlip("ShipIcon", 0)

    def SetTargetBracket(self, blip: _RadarBlip) -> None:
        self._target_bracket = blip

    def GetTargetBracket(self) -> Optional[_RadarBlip]:
        return self._target_bracket


class _RadarDisplay:
    """SDK App.py:8513 — extends STStylizedWindow. The shim implements
    only the methods bridge-load scripts touch; the visual is rendered
    by SensorsPanel reading game state directly, not by walking this
    object's children.

    Child slot 0 (App.RadarDisplay.RADAR_SCOPE) is the one RadarScope
    instance SDK RadarDisplay.Create adds. Exposed as a class constant
    so SDK lookups via App.RadarDisplay.RADAR_SCOPE resolve."""

    RADAR_SCOPE = 0

    def __init__(self, w: float = 0.0, h: float = 0.0):
        self._w = float(w)
        self._h = float(h)
        self._name: str = ""
        self._children: List[object] = []
        self._minimized: bool = False
        self._minimizable: bool = True
        self._visible: bool = True
        # Range chosen by feel; original BC value is opaque (closed
        # Appc.dll). See docs/instrumented_experiments/2026-05-26-radar-range-calibration.md
        # for the planned measurement experiment.
        self._range_gu: float = 1000.0

    # STStylizedWindow / window-shaped surface.
    def SetName(self, name) -> None:    self._name = str(name)
    def GetName(self) -> str:           return self._name
    def GetWidth(self) -> float:        return self._w
    def GetHeight(self) -> float:       return self._h
    def SetUseScrolling(self, _flag: int) -> None: pass
    def SetColorBasedOnFlags(self) -> None: pass
    def ResizeUI(self) -> None: pass
    def RepositionUI(self) -> None: pass
    def InteriorChangedSize(self, _flag: int = 0) -> None: pass
    def SetPosition(self, _x: float, _y: float, _z: int = 0) -> None: pass
    def Layout(self) -> None: pass

    def AddChild(self, child, _x: float = 0.0, _y: float = 0.0, _z: int = 0) -> None:
        self._children.append(child)

    def GetNthChild(self, n: int):
        if 0 <= n < len(self._children):
            return self._children[n]
        return None

    # Minimizable surface (TacticalControlWindow Setup* functions call these).
    def IsMinimized(self) -> int:        return 1 if self._minimized else 0
    def SetMinimized(self, v) -> None:   self._minimized = bool(v)
    def IsMinimizable(self) -> int:      return 1 if self._minimizable else 0
    def SetMinimizable(self, v) -> None: self._minimizable = bool(v)

    def IsVisible(self) -> int:           return 1 if self._visible else 0
    def SetVisible(self, _flag: int = 0) -> None:    self._visible = True
    def SetNotVisible(self, _flag: int = 0) -> None: self._visible = False
    def GetObjID(self) -> int:            return id(self)

    # Engine-side accessor the SensorsPanel reads (not an SDK call —
    # SetRange lets mission scripts override the default if they want).
    def SetRange(self, range_gu: float) -> None:
        self._range_gu = float(range_gu)

    def GetRange(self) -> float:
        return self._range_gu


# ── Module-level factories (re-exported by App.py) ──

def RadarDisplay_Create(w: float = 0.0, h: float = 0.0) -> _RadarDisplay:
    return _RadarDisplay(w=w, h=h)


def RadarScope_Create(w: float = 0.0, h: float = 0.0) -> _RadarScope:
    return _RadarScope(w=w, h=h)


def RadarBlip_Create(group_name: str = "", index: int = 0) -> _RadarBlip:
    return _RadarBlip(group_name=group_name, index=index)


def RadarDisplay_Cast(obj):
    """Lenient cast — matches the STMenu_Cast pattern used elsewhere in
    the shim."""
    if isinstance(obj, _RadarDisplay):
        return obj
    return obj if obj is not None else None
