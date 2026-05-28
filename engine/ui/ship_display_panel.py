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
    SetXxxDisplay. Before adoption, the parent ref is None and
    invalidation signals are silently dropped. Adoption (via
    `ShipDisplayPanel.SetXxxDisplay`) wires the parent ref and
    subsequent mutations propagate.
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
    def GetHeight(self) -> float: return 0.0
    def GetWidth(self) -> float: return 0.0
    def SetPosition(self, *args, **kwargs) -> None: pass


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
    def GetShieldsDisplay(self) -> "_ShieldsSubview": return self._shields
    def GetDamageDisplay(self)  -> "_DamageSubview":  return self._damage
    def GetHealthGauge(self)    -> "_HullGaugeSubview": return self._gauge

    def SetShieldsDisplay(self, subview: "_ShieldsSubview") -> None:
        self._shields.parent = None
        subview.parent = self
        self._shields = subview
        self._last_snapshot = None

    def SetDamageDisplay(self, subview: "_DamageSubview") -> None:
        self._damage.parent = None
        subview.parent = self
        self._damage = subview
        self._last_snapshot = None

    def SetHealthGauge(self, subview: "_HullGaugeSubview") -> None:
        self._gauge.parent = None
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
    def AddChild(self, *args, **kwargs) -> None: pass

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

    def _snapshot(self) -> tuple:
        ship = _resolve_ship_for_role(self._role)
        if ship is None:
            return (None, "", "NONE", "", 0.0, (0.0,) * 6, (),
                    None, None, self._minimized, False)
        ship_id      = ship.GetObjID() if hasattr(ship, "GetObjID") else 0
        name         = ship.GetName() if hasattr(ship, "GetName") else ""
        affiliation  = _affiliation_for(ship)
        species_key  = _species_key_for(ship)
        hull_pct     = _hull_pct(ship)
        shields_pct  = _shields_tuple(ship)
        damage       = _damage_states(ship)
        range_m, speed_kph = (None, None)
        if self._role == ROLE_TARGET:
            range_m, speed_kph = _range_and_speed_to(ship)
        return (ship_id, name, affiliation, species_key, hull_pct,
                shields_pct, damage, range_m, speed_kph,
                self._minimized, True)

    # Panel framework ---------------------------------------------------
    def render_payload(self) -> Optional[str]:
        return None  # filled in Task 5

    def dispatch_event(self, action: str) -> bool:
        return False  # filled in Task 6

    def invalidate(self) -> None:
        self._last_snapshot = None


# ---------------------------------------------------------------------
# Snapshot generation helpers
# ---------------------------------------------------------------------

_DAMAGE_SUBSYSTEM_ORDER = ("Engines", "Weapons", "Sensors", "Shield Generator")


def _get_player():
    """Returns the current player ship, or None."""
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _resolve_ship_for_role(role: str):
    """Returns the ship the panel renders for, or None for the no-target /
    unknown-target empty state."""
    player = _get_player()
    if player is None:
        return None
    if role == ROLE_PLAYER:
        return player
    # target role
    target = player.GetTarget() if hasattr(player, "GetTarget") else None
    if target is None:
        return None
    # Sensor-knowledge gate (matches SDK ShieldsDisplay.SetShipIcon at
    # sdk/Build/scripts/Tactical/Interface/ShieldsDisplay.py:329-338).
    try:
        sensors = player.GetSensorSubsystem()
        if sensors is not None and sensors.IsObjectKnown(target) == 0:
            return None
    except Exception:
        pass
    return target


def _affiliation_for(ship) -> str:
    """Map ship affiliation to the snapshot string used by the CSS layer."""
    try:
        player = _get_player()
        if player is None or ship is None:
            return "NONE"
        if ship is player:
            return "FRIENDLY"
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        episode = game.GetCurrentEpisode() if game else None
        mission = episode.GetCurrentMission() if episode else None
        if mission is not None:
            for kind, group_getter in (
                ("FRIENDLY", "GetFriendlyGroup"),
                ("ENEMY",    "GetEnemyGroup"),
                ("NEUTRAL",  "GetNeutralGroup"),
            ):
                group = getattr(mission, group_getter, lambda: None)()
                if group is not None and group.HasName(ship.GetName()):
                    return kind
    except Exception:
        pass
    return "UNKNOWN"


def _species_key_for(ship) -> str:
    """Returns the species short name (e.g. 'Galaxy') for silhouette lookup."""
    try:
        prop = ship.GetShipProperty()
        return prop.GetSpeciesName() if prop else ""
    except Exception:
        return ""


def _hull_pct(ship) -> float:
    try:
        hull = ship.GetHull()
        if hull is None:
            return 0.0
        mx = hull.GetMaxCondition()
        if mx <= 0:
            return 0.0
        return float(hull.GetCondition()) / float(mx)
    except Exception:
        return 0.0


def _shields_tuple(ship):
    try:
        sh = ship.GetShieldSubsystem()
        if sh is None:
            return (0.0,) * 6
        return tuple(sh.GetSingleShieldPercentage(f) for f in range(sh.NUM_SHIELDS))
    except Exception:
        return (0.0,) * 6


def _damage_states(ship):
    """Walks Engines, Weapons, Sensors, Shield Generator. Healthy = omitted."""
    out = []
    getters = (
        ("Engines",          "GetImpulseEngineSubsystem"),
        ("Weapons",          "GetPhaserSystem"),
        ("Sensors",          "GetSensorSubsystem"),
        ("Shield Generator", "GetShieldSubsystem"),
    )
    for label, getter_name in getters:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        try:
            sub = getter()
        except Exception:
            continue
        if sub is None:
            continue
        state = _subsystem_state(sub)
        if state is not None:
            out.append((label, state))
    return tuple(out)


def _subsystem_state(sub):
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
    except Exception:
        pass
    return None


def _range_and_speed_to(ship):
    """Returns (range_m, speed_kph) for the target panel; None,None on error."""
    try:
        player = _get_player()
        if player is None or ship is None:
            return None, None
        p1 = player.GetTranslate(); p2 = ship.GetTranslate()
        dx = p1.x - p2.x; dy = p1.y - p2.y; dz = p1.z - p2.z
        rng_m = (dx*dx + dy*dy + dz*dz) ** 0.5
        # Speed: |velocity| in metres/sec → km/h
        vel = ship.GetLinearVelocity() if hasattr(ship, "GetLinearVelocity") else None
        if vel is None:
            speed_kph = 0.0
        else:
            speed_ms = (vel.x*vel.x + vel.y*vel.y + vel.z*vel.z) ** 0.5
            speed_kph = speed_ms * 3.6
        return rng_m, speed_kph
    except Exception:
        return None, None
