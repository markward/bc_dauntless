"""CEF view for the SDK ShipDisplay widget.

The SDK creates two ShipDisplay widgets per game (player + target).
Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

from typing import Optional

from engine.ui.panel import Panel


ROLE_PLAYER = "player"
ROLE_TARGET = "target"
_VALID_ROLES = (ROLE_PLAYER, ROLE_TARGET)


class _SubviewBase:
    """Common base — sub-views forward mutations to the parent panel.

    The SDK constructs sub-views via factory calls BEFORE adoption
    (parent=None), then the parent ShipDisplay adopts them via
    SetXxxDisplay. Until adoption, mutations are buffered locally and
    take effect when the parent is wired in.
    """
    def __init__(self, parent: Optional["ShipDisplayPanel"]):
        self.parent: Optional["ShipDisplayPanel"] = parent

    def _invalidate(self) -> None:
        if self.parent is not None:
            self.parent._last_snapshot = None

    # SDK layout/visibility no-ops (CSS owns layout).
    def Resize(self, *args, **kwargs) -> None: pass
    def Layout(self, *args, **kwargs) -> None: pass
    def SetSkipParent(self, *args, **kwargs) -> None: pass
    def SetVisible(self, *args, **kwargs) -> None: pass
    def SetNotVisible(self, *args, **kwargs) -> None: pass
    def SetBatchChildPolys(self, *args, **kwargs) -> None: pass
    def RemoveEvents(self, *args, **kwargs) -> None: pass


class _ShieldsSubview(_SubviewBase):
    def UpdateForNewShip(self) -> None:
        self._invalidate()


class _DamageSubview(_SubviewBase):
    def UpdateForNewShip(self) -> None:
        self._invalidate()
    def RepositionUI(self, *args, **kwargs) -> None: pass
    def HideIcons(self, *args, **kwargs) -> None: pass
    def ShowIcons(self, *args, **kwargs) -> None: pass


class _HullGaugeSubview(_SubviewBase):
    def __init__(self, parent: Optional["ShipDisplayPanel"]):
        super().__init__(parent)
        self._object = None
    def SetObject(self, hull) -> None:
        self._object = hull
        self._invalidate()
    def SetFillColor(self, *args, **kwargs) -> None: pass
    def SetEmptyColor(self, *args, **kwargs) -> None: pass


class ShipDisplayPanel(Panel):
    def __init__(self, role: str):
        super().__init__()
        assert role in _VALID_ROLES, "role must be 'player' or 'target'"
        self._role: str = role
        self._ship_id: int = 0  # App.NULL_ID — bound in Task 4
        self._last_snapshot: Optional[tuple] = None
        self._minimizable: bool = (role == ROLE_TARGET)
        self._minimized: bool = False
        self._shields = _ShieldsSubview(parent=self)
        self._damage  = _DamageSubview(parent=self)
        self._gauge   = _HullGaugeSubview(parent=self)

    @property
    def name(self) -> str:
        return "ship-" + self._role

    # SDK widget API ----------------------------------------------------
    def SetShipID(self, ship_id) -> None:
        self._ship_id = int(ship_id)
        self._last_snapshot = None  # force re-emit on next tick

    def SetShipIDVar(self, ship_id) -> None:
        """SDK alias used by ShipDisplay.SetShipID at line 148."""
        self._ship_id = int(ship_id)
        self._last_snapshot = None

    def GetShipID(self) -> int:
        return self._ship_id

    def SetMinimizable(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimizable = bool(value)
            self._last_snapshot = None

    def SetMinimized(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimized = bool(value)
            self._last_snapshot = None

    def IsMinimized(self) -> int:
        return 1 if self._minimized else 0

    def IsMinimizable(self) -> int:
        return 1 if self._minimizable else 0

    # Sub-view getters/adopters -----------------------------------------
    def GetShieldsDisplay(self): return self._shields
    def GetDamageDisplay(self):  return self._damage
    def GetHealthGauge(self):    return self._gauge

    def SetShieldsDisplay(self, subview: "_ShieldsSubview") -> None:
        subview.parent = self
        self._shields = subview
        self._last_snapshot = None

    def SetDamageDisplay(self, subview: "_DamageSubview") -> None:
        subview.parent = self
        self._damage = subview
        self._last_snapshot = None

    def SetHealthGauge(self, subview: "_HullGaugeSubview") -> None:
        subview.parent = self
        self._gauge = subview
        self._last_snapshot = None

    # SDK layout/chrome no-ops. The SDK construction path at
    # sdk/Build/scripts/Tactical/Interface/ShipDisplay.py:79-100 calls
    # these on the parent ShipDisplay — they must exist or construction
    # crashes. CSS owns layout, so they don't do anything except return
    # sensible defaults.
    def SetFixedSize(self, *args, **kwargs) -> None: pass
    def SetMaximumSize(self, *args, **kwargs) -> None: pass
    def SetPosition(self, *args, **kwargs) -> None: pass
    def Resize(self, *args, **kwargs) -> None: pass
    def AlignTo(self, *args, **kwargs) -> None: pass
    def Layout(self, *args, **kwargs) -> None: pass
    def InteriorChangedSize(self, *args, **kwargs) -> None: pass
    def SetBatchChildPolys(self, *args, **kwargs) -> None: pass
    def SetUseFocusGlass(self, *args, **kwargs) -> None: pass
    def SetNoFocus(self, *args, **kwargs) -> None: pass
    def SetAlwaysHandleEvents(self, *args, **kwargs) -> None: pass

    # Dimension getters return per-role constants so SDK chained math
    # (e.g. RepositionUI's "anchor to corner, chain by widths") resolves
    # without crashing. Values are not authoritative for layout.
    def GetLeft(self)         -> float: return 0.0
    def GetTop(self)          -> float: return 0.0
    def GetWidth(self)        -> float: return 0.2
    def GetHeight(self)       -> float: return 0.2
    def GetBorderWidth(self)  -> float: return 0.0
    def GetBorderHeight(self) -> float: return 0.0
    def GetMaximumInteriorWidth(self)  -> float: return 0.2
    def GetMaximumInteriorHeight(self) -> float: return 0.2

    # GetInteriorPane returns a sentinel that quacks like a pane —
    # the SDK only ever calls Resize/Layout on it, both no-ops.
    def GetInteriorPane(self):
        return self._gauge  # any _SubviewBase instance will accept Resize

    # Panel framework ---------------------------------------------------
    def render_payload(self) -> Optional[str]:
        return None  # filled in Task 5

    def dispatch_event(self, action: str) -> bool:
        return False  # filled in Task 6

    def invalidate(self) -> None:
        self._last_snapshot = None
