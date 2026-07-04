"""CEF view for the SDK ShipDisplay widget.

The SDK creates two ShipDisplay widgets per game (player + target).
Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.ui import ship_icons
from engine.ui.species_icons import stem_for_species
import engine.dev_mode as dev_mode


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
    def GetConceptualParent(self):
        return self.parent


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
        # Both roles can minimize (user-driven UX; the SDK's role gate
        # on SetMinimized predates our CEF UI). Player honours
        # SetMinimizable so SDK scripts can still hard-disable if needed.
        self._minimizable: bool = True
        self._minimized: bool = False
        self._visible: bool = True
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
        self._minimizable = bool(value)
        self._last_snapshot = None

    def SetMinimized(self, value) -> None:
        self._minimized = bool(value)
        self._last_snapshot = None

    def IsMinimized(self) -> int:
        return 1 if self._minimized else 0

    def IsMinimizable(self) -> int:
        return 1 if self._minimizable else 0

    # SDK visibility API — mirrors what TacticalControlWindow.py:441
    # calls on pEnemyShipDisplay. Tracks a Python-side _visible flag
    # separate from CSS hidden so SDK queries get a sensible answer.
    def SetVisible(self, *args, **kwargs) -> None:
        self._visible = True
        self._last_snapshot = None

    def SetNotVisible(self, *args, **kwargs) -> None:
        self._visible = False
        self._last_snapshot = None

    def IsVisible(self) -> int:
        return 1 if self._visible else 0

    def GetObjID(self) -> int:
        """SDK identity. Stable for the panel's lifetime; not a real
        TGObject ID but distinct per instance."""
        return id(self) & 0x7FFFFFFF  # positive 31-bit int for SDK compat

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
    def SetUseScrolling(self, *args, **kwargs) -> None: pass
    def SetName(self, name: str = "") -> None: pass
    def GetConceptualParent(self):
        """SDK uses this for sub-views to walk back to the owning panel.
        On the panel itself, return None — there is no parent panel."""
        return None

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
        # self._visible is driven by the host loop's view-mode wiring —
        # False while in bridge view, True in exterior/tactical. When
        # False, the JS payload's visible=False hides the panel entirely.
        if not self._visible:
            return (None, "", "NONE", "", 0.0, (0.0,) * 6, (),
                    None, None, self._minimized, False)
        ship = _resolve_ship_for_role(self._role)
        if ship is None:
            return (None, "", "NONE", "", 0.0, (0.0,) * 6, (),
                    None, None, self._minimized, False)
        player       = _get_player()
        ship_id      = ship.GetObjID() if hasattr(ship, "GetObjID") else 0
        name         = ship.GetName() if hasattr(ship, "GetName") else ""
        affiliation  = _affiliation_for(ship, player)
        species_key  = _species_key_for(ship)
        hull_pct     = _hull_pct(ship)
        shields_pct  = _shields_tuple(ship)
        damage_icons_list = _damage_icon_descriptors(ship)
        # Frozen form for snapshot equality. Position2D / icon_num
        # don't change at runtime, so bucket state only — that's the
        # field that actually flips frame-to-frame.
        damage_frozen = tuple(
            (d["icon_num"], d["x_px"], d["y_px"], d["state"])
            for d in damage_icons_list
        )
        range_km, speed_kph = (None, None)
        if self._role == ROLE_TARGET:
            range_km, speed_kph = _range_and_speed_to(ship, player)
        return (ship_id, name, affiliation, species_key, hull_pct,
                shields_pct, damage_frozen, range_km, speed_kph,
                self._minimized, True)

    # Panel framework ---------------------------------------------------
    def render_payload(self) -> Optional[str]:
        snap = self._snapshot()
        if snap == self._last_snapshot:
            return None
        self._last_snapshot = snap
        (ship_id, name, affiliation, species, hull_pct,
         shields, damage_frozen, range_km, speed_kph,
         minimized, visible) = snap
        ship_now = _resolve_ship_for_role(self._role) if visible else None
        damage_icons_list = _damage_icon_descriptors(ship_now) if ship_now else []
        payload = {
            "visible":      visible,
            "ship_name":    name,
            "affiliation":  affiliation,
            "species":      species,
            "hull_pct":     hull_pct,
            "shields_pct":  list(shields),
            "damage_icons": damage_icons_list,
            "range_km":     range_km,
            "speed_kph":    speed_kph,
            "minimized":    minimized,
        }
        payload["silhouette_url"] = ship_icons.icon_path_for_species(payload["species"])
        return ("setShipDisplay(" + json.dumps(self._role) + ", " +
                json.dumps(payload) + ");")

    def dispatch_event(self, action: str) -> bool:
        if action == "minimize-toggle":
            self._minimized = not self._minimized
            self._last_snapshot = None
            return True
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None


# ---------------------------------------------------------------------
# Snapshot generation helpers
# ---------------------------------------------------------------------

def _get_player():
    """Returns the current player ship, or None."""
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _current_episode():
    """Returns the current episode, or None if no game is loaded."""
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetCurrentEpisode() if game else None
    except Exception:
        return None


def player_sensors_offline() -> bool:
    """True iff the player's own SensorSubsystem reports IsDisabled or
    IsDestroyed. Used to gate target-list visibility, IFF colouring, and
    target-panel resolution. Spec §4.3."""
    from engine.appc.subsystems import _is_offline
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game else None
    if player is None:
        return False
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    return _is_offline(sensors)


def _resolve_ship_for_role(role: str):
    """Returns the ship the panel renders for, or None for the no-target
    empty state.

    The SDK gates target display behind SensorSubsystem.IsObjectKnown()
    (ShieldsDisplay.SetShipIcon at sdk/Build/scripts/Tactical/Interface/
    ShieldsDisplay.py:329-338). Our Phase 1 sensor subsystem doesn't
    populate the known-objects set yet — nothing scans for contacts —
    so applying the gate would silently block every target. Trust
    SetTarget for now; revisit when sensor scanning lands.

    Project 5 sensor gate (§4.3): when the player's sensors are offline,
    target-role resolves to None (panel goes to empty state). Player
    role is unaffected — you always know who you are.
    """
    player = _get_player()
    if player is None:
        return None
    if role == ROLE_PLAYER:
        return player
    if player_sensors_offline():
        return None
    target = player.GetTarget() if hasattr(player, "GetTarget") else None
    return target


def _affiliation_for(ship, player) -> str:
    """Map ship affiliation to the snapshot string used by the CSS layer.

    Project 5 sensor gate (§4.3): when the player's own sensors are
    offline, every non-player ship maps to UNKNOWN. Player-self
    short-circuits FRIENDLY above this check so you can always see who
    you are.
    """
    try:
        if player is None or ship is None:
            return "NONE"
        if ship is player:
            return "FRIENDLY"
        if player_sensors_offline():
            return "UNKNOWN"
        episode = _current_episode()
        mission = episode.GetCurrentMission() if episode else None
        if mission is not None:
            for kind, group_getter in (
                ("FRIENDLY", "GetFriendlyGroup"),
                ("ENEMY",    "GetEnemyGroup"),
                ("NEUTRAL",  "GetNeutralGroup"),
            ):
                group = getattr(mission, group_getter, lambda: None)()
                if group is not None and group.IsNameInGroup(ship.GetName()):
                    return kind
    except Exception as _e:
        dev_mode.log_swallowed("resolve ship allegiance", _e)
    return "UNKNOWN"


def _species_key_for(ship) -> str:
    """Returns the TGA filename stem (e.g. 'Galaxy', 'BirdOfPrey') for
    the ship's species, or '' when no icon is registered.

    Phase 1 ships expose `GetSpecies()` returning the integer enum
    from sdk/Build/scripts/Multiplayer/SpeciesToShip.py; we map that
    to the filename stem from sdk/Build/scripts/Icons/ShipIcons.py via
    species_icons.stem_for_species.
    """
    try:
        if not hasattr(ship, "GetSpecies"):
            return ""
        species_int = ship.GetSpecies()
        if not isinstance(species_int, int):
            return ""
        stem = stem_for_species(species_int)
        return stem if stem else ""
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


def _shields_tuple(ship) -> tuple[float, ...]:
    try:
        sh = ship.GetShieldSubsystem()
        if sh is None:
            return (0.0,) * 6
        return tuple(sh.GetSingleShieldPercentage(f) for f in range(sh.NUM_SHIELDS))
    except Exception:
        return (0.0,) * 6


# Source getters for the hardpoint walk. Each getter returns either
# a single subsystem or None. We recurse into children to pick up
# per-bank phasers, per-tube torpedoes, etc. — those carry their own
# Position2D from the hardpoint.
_DAMAGE_SOURCE_GETTERS = (
    "GetHull",
    "GetSensorSubsystem",
    "GetShieldSubsystem",
    "GetImpulseEngineSubsystem",
    "GetWarpEngineSubsystem",
    "GetPowerSubsystem",
    "GetRepairSubsystem",
    "GetCloakingSubsystem",
    "GetPhaserSystem",
    "GetTorpedoSystem",
    "GetPulseWeaponSystem",
    "GetTractorBeamSystem",
)


def _iter_damage_subsystems(ship):
    """Yield every ShipSubsystem reachable from ``ship`` via the
    standard damage source getters, recursing into child subsystems
    so per-bank phasers and per-tube torpedoes surface alongside
    their parent weapon systems. No filtering here — the caller
    decides which rows to render."""
    if ship is None:
        return
    seen = set()
    for getter_name in _DAMAGE_SOURCE_GETTERS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        try:
            sub = getter()
        except Exception:
            continue
        if sub is None or id(sub) in seen:
            continue
        seen.add(id(sub))
        yield sub
        try:
            n = sub.GetNumChildSubsystems()
        except Exception:
            continue
        for i in range(n):
            try:
                child = sub.GetChildSubsystem(i)
            except Exception:
                continue
            if child is None or id(child) in seen:
                continue
            seen.add(id(child))
            yield child


def _damage_icon_descriptors(ship):
    """Per-row descriptors for the damage overlay. Filters to
    subsystems with a non-zero Position2D — the SDK uses (0, 0) to
    mean "don't display." Each descriptor:

        {
          "icon_num": int,        # DamageIcons enum value
          "icon_svg": str | None, # inline SVG, or None if no glyph available
          "x_px":    float,       # hardpoint pixel coord, SDK 640x480 frame
          "y_px":    float,
          "state":   "healthy" | "damaged" | "disabled" | "destroyed",
        }
    """
    from engine.ui import damage_icons
    out: list[dict] = []
    for sub in _iter_damage_subsystems(ship):
        try:
            pos = sub.GetPosition2D()
        except Exception:
            continue
        if not isinstance(pos, tuple) or len(pos) != 2:
            continue
        x_px, y_px = float(pos[0]), float(pos[1])
        if x_px == 0.0 and y_px == 0.0:
            continue
        icon_num = damage_icons.icon_num_for_subsystem(sub)
        out.append({
            "icon_num": icon_num,
            "icon_svg": damage_icons.icon_svg_for_num(icon_num),
            "x_px":     x_px,
            "y_px":     y_px,
            "state":    _row_state(sub),
        })
    return out


def _row_state(sub) -> str:
    """Predicate ladder — "healthy" instead of None so the panel always
    has a class to apply. Healthy → default colour; damaged/disabled/
    destroyed → --bc-damage-* CSS tokens."""
    try:
        if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "IsDamaged") and sub.IsDamaged():
            return "damaged"
    except Exception as _e:
        dev_mode.log_swallowed("subsystem health state", _e)
    return "healthy"


def _range_and_speed_to(ship, player):
    """Returns (range_km, speed_kph) for the target panel; None,None on error.

    Positions and velocities are read in BC's internal game units (GU);
    convert to km / kph at this display boundary via engine.units.

    Range is the distance to the target's BOUNDING SPHERE, not its centre —
    BC's readout convention (confirmed live: orbiting Haven, radius 90 GU,
    the original game reads ~25 km = the authored radius+150 GU orbit
    measured from the surface). Negligible for small ships, decisive for
    planets/stations.
    """
    from engine.units import GU_TO_KM, GUPS_TO_KPH
    try:
        if player is None or ship is None:
            return None, None
        p1 = player.GetTranslate(); p2 = ship.GetTranslate()
        dx = p1.x - p2.x; dy = p1.y - p2.y; dz = p1.z - p2.z
        rng_gu = (dx*dx + dy*dy + dz*dz) ** 0.5
        radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 0.0
        rng_gu = rng_gu - radius if rng_gu > radius else 0.0
        range_km = rng_gu * GU_TO_KM
        vel = ship.GetVelocityTG() if hasattr(ship, "GetVelocityTG") else None
        if vel is None:
            speed_kph = 0.0
        else:
            speed_gups = (vel.x*vel.x + vel.y*vel.y + vel.z*vel.z) ** 0.5
            speed_kph = speed_gups * GUPS_TO_KPH
        return range_km, speed_kph
    except Exception:
        return None, None
