"""ShipSubsystem hierarchy.

Mirrors sdk/Build/scripts/App.py:5578-7000 — runtime instances of the
property templates defined in engine/appc/properties.py.  Properties hold
the design-time data (mass, max condition, position); subsystems hold
the per-ship per-instance state (current condition, firing state, target).

Phase 1 ships rarely create subsystems explicitly — they live behind
``ShipClass.GetTorpedoSystem()`` etc., which return None by default until
``loadspacehelper`` populates them in Phase 2.  These classes exist so
that the few SDK call sites that DO obtain a subsystem (Bridge handlers,
mission scripts wiring weapon-fire events) get a real object with the
expected method surface rather than a NamedStub.
"""

import math as _math

from engine.appc.events import TGEventHandlerObject
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.math import TGPoint3, TGMatrix3
import engine.dev_mode as dev_mode


def subsystem_world_position(sub, ship=None):
    """World mount point of a subsystem: ship_loc + R · local_mount.

    Column-vector rotation convention (R · v); NO scale — BC stores mounts
    in world units relative to the ship centre. Returns the ship location if
    the subsystem has no 3D mount, and the origin if no ship is resolvable.

    ``ship`` may be passed explicitly (required for the Hull/root subsystem,
    whose ``_climb_to_ship()`` returns None).
    """
    if ship is None:
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
            offset.MultMatrixLeft(rot)   # R · offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)


def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed, OR its parent ship is
    out of action (dying/dead — inert coast). Single source of truth for the
    capability gates (weapons, engines, sensors, shield generator, repair).
    Reads predicates at use-time so repair lifting condition releases the gate
    automatically on the next call."""
    if sub is None:
        return False
    if bool(sub.IsDisabled()) or bool(sub.IsDestroyed()):
        return True
    if hasattr(sub, "GetParentShip"):
        from engine.appc import ship_death
        if ship_death._out_of_action(sub.GetParentShip()):
            return True
    return False


def impulse_online_fraction(ies) -> float:
    """Fraction in [0, 1] of a ship's impulse engine pods that are online.

    `ies` is the master ImpulseEngineSubsystem (or None). A pod is offline
    iff _is_offline(pod) (disabled OR destroyed). Returns:
      - 1.0 when ies is None or has no child pods (fallback ships);
      - 0.0 when the master itself is offline;
      - online_pods / total_pods otherwise.
    """
    if ies is None:
        return 1.0
    if _is_offline(ies):
        return 0.0
    n = ies.GetNumChildSubsystems()
    if n == 0:
        return 1.0
    online = sum(
        1 for i in range(n) if not _is_offline(ies.GetChildSubsystem(i))
    )
    return online / float(n)


def active_impulse_emitters(player) -> list:
    """Active impulse-engine pods as wake emitters.

    Returns ``[{"key": int, "pos": (x, y, z), "size": float}]`` — one entry per
    ONLINE pod (not ``_is_offline``), positioned at its world mount and sized by
    its radius. Empty when there is no player, no impulse subsystem, or the
    master impulse subsystem is offline. When the master is online but exposes
    no child pods, falls back to a single emitter at the master's own mount so
    such ships still trail a wake. Read-only; safe to call every frame.
    """
    if player is None or not hasattr(player, "GetImpulseEngineSubsystem"):
        return []
    ies = player.GetImpulseEngineSubsystem()
    if ies is None or _is_offline(ies):
        return []

    emitters = []
    n = ies.GetNumChildSubsystems() if hasattr(ies, "GetNumChildSubsystems") else 0
    for i in range(n):
        pod = ies.GetChildSubsystem(i)
        if pod is None or _is_offline(pod):
            continue
        wp = subsystem_world_position(pod, player)
        radius = float(pod.GetRadius()) if hasattr(pod, "GetRadius") else 0.0
        # key = id(pod): safe as a per-emitter handle — pods are long-lived
        # per-mission objects, the tracker drops an emitter once its trail
        # empties (a reused id just starts a fresh trail), and reset_sdk_globals
        # clears the tracker on mission swap. Never used to compare across runs.
        emitters.append({"key": id(pod), "pos": (wp.x, wp.y, wp.z), "size": radius})

    if not emitters:
        # No discoverable online pods — fall back to the master mount so the
        # ship still trails a single wake while impulse is online.
        wp = subsystem_world_position(ies, player)
        radius = float(ies.GetRadius()) if hasattr(ies, "GetRadius") else 0.0
        emitters.append({"key": id(ies), "pos": (wp.x, wp.y, wp.z), "size": radius})
    return emitters


class ShipSubsystem(TGEventHandlerObject):
    def __init__(self, name: str = ""):
        super().__init__()
        self._name = name
        self._property = None
        self._parent_ship = None
        self._parent_subsystem = None
        self._child_subsystem = None
        self._children: list["ShipSubsystem"] = []
        self._condition = 1.0
        self._max_condition = 1.0
        # Lazily-created FloatRangeWatcher on GetConditionPercentage(),
        # handed out by GetCombinedPercentageWatcher() (Bridge/Characters/
        # Brex.py:108 registers hull-status thresholds on it). Lazy so the
        # thousands of subsystems that never hand one out pay nothing.
        self._combined_watcher = None
        self._radius = 0.0
        self._position = TGPoint3(0.0, 0.0, 0.0)
        # Body-space mounting axes — defaults match the SDK convention
        # (firing along +Y, right side along +X, up along +Z).
        # SetProperty mirrors the hardpoint values across when a property
        # is bound (forward=Direction, up=Up, right=up×forward).
        self._direction = TGPoint3(0.0, 1.0, 0.0)
        self._right     = TGPoint3(1.0, 0.0, 0.0)
        self._up        = TGPoint3(0.0, 0.0, 1.0)
        # Arc/damage data mirrored from EnergyWeaponProperty.  Defaults
        # leave the gate fully open so non-arc emitters (torpedo tubes)
        # don't get accidentally restricted.
        import math as _math
        self._arc_width_lo:  float = -_math.pi
        self._arc_width_hi:  float =  _math.pi
        self._arc_height_lo: float = -_math.pi / 2
        self._arc_height_hi: float =  _math.pi / 2
        self._max_damage:          float = 0.0
        self._max_damage_distance: float = 0.0
        # Mirrored from WeaponProperty.SetDamageRadiusFactor.  Used by
        # weapon_splash_radius() to resolve the hit sphere.  0.0 = not set
        # (caller falls back to payload DRF or phaser default 0.15).
        self._damage_radius_factor: float = 0.0
        # Phaser-strip arc radius from Position (0 = point emitter).
        # SDK SetLength: distance from the strip's curvature centre to
        # the rim along the firing direction. See research doc § Bug D.
        self._length:              float = 0.0
        # Phaser-strip lateral dimension perpendicular to Length.
        # Mirrored from EnergyWeaponProperty.SetWidth; distinct from
        # _phaser_width (the beam thickness).
        self._width:               float = 0.0
        # Texture tiles per world unit along the beam (0 = stretch once).
        self._length_texture_tile_per_unit: float = 0.0
        # Phaser-specific beam geometry — mirrored from PhaserProperty.
        # 0 on non-phaser subsystems; descriptor builder gates on these.
        self._phaser_width: float = 0.0
        self._main_radius:  float = 0.0
        self._core_scale:   float = 0.0
        # Phaser beam colours (RGBA tuples).  Neutral defaults are fine
        # because the bank only emits beams when SetProperty has populated
        # them from a PhaserProperty hardpoint.
        self._outer_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_shell_color: tuple = (1.0, 1.0, 1.0, 1.0)
        self._outer_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        self._inner_core_color:  tuple = (1.0, 1.0, 1.0, 1.0)
        self._texture_name: str = ""
        # Prism geometry + taper + scroll — full BC-faithful set.
        self._num_sides: int = 6
        self._taper_radius: float = 0.01
        self._taper_ratio: float = 0.25
        self._taper_min_length: float = 5.0
        self._taper_max_length: float = 30.0
        self._perimeter_tile: float = 1.0
        self._texture_speed: float = 0.0
        # Flag set True only when a property actually supplied typed arc
        # data (EnergyWeaponProperty hierarchy).  Emitters without it
        # (torpedo tubes) fall back to a 90° dot-product cone.
        self._arc_set: bool = False
        # Shared identity fields populated by SetupProperties.
        self._critical: int = 0
        # Default targetable so a subsystem whose hardpoint never set the flag
        # still shows/targets; SetupProperties copies the property's value on
        # top (SubsystemProperty defaults to 1 as well). IsTargetable() reads
        # this field — a hardpoint SetTargetable(0) (e.g. an asteroid's Shield
        # Generator / Power Plant) is what hides a subsystem from the menu.
        self._targetable: int = 1
        self._primary: int = 0
        self._disabled_percentage: float = 0.25
        # Explicit damage/destroyed flags.  SetDamaged/SetDestroyed let tests
        # and the damage system force these states independently of _condition;
        # the predicate methods also fall back to condition-based derivation so
        # both paths stay consistent (e.g. applying condition damage will also
        # make IsDestroyed() true when condition hits zero).
        self._damaged: bool = False
        self._destroyed: bool = False
        # WeaponsDisplay icon descriptor mirrored from SubsystemProperty.
        # The ShipDisplay panel snapshot reads these without walking back
        # to the property template. Coordinates are pixel-space against
        # the SDK's 640x480 reference; the panel divides at the display
        # boundary. _icon_num == 0 is the "no icon" sentinel (matches the
        # SDK Destroyed-slot fallback in Icons/WeaponIcons.py:55-56) —
        # tractor beams and GenericTemplate emitters set it explicitly so
        # the panel can skip them cleanly.
        self._icon_num: int = 0
        self._icon_position_x_px: float = 0.0
        self._icon_position_y_px: float = 0.0
        self._icon_above_ship: int = 0
        self._indicator_icon_num: int = 0
        self._indicator_icon_position_x_px: float = 0.0
        self._indicator_icon_position_y_px: float = 0.0
        # DamageDisplay panel coord (pixel-space against SDK's 640x480
        # reference). Mirrored from SubsystemProperty.SetPosition2D.
        self._position_2d: tuple = (0.0, 0.0)

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def GetDisplayName(self) -> str:
        # SDK: Appc.ShipSubsystem_GetDisplayName (App.py:5591) — localized
        # TGString. Our subsystem _names are already the human-readable
        # hardpoint names ("Port Nacelle"), so return _name, matching the
        # ObjectClass.GetDisplayName fallback. Must be defined here (not
        # inherited): ShipSubsystem extends TGEventHandlerObject, not
        # ObjectClass, and TGObject.__getattr__ would vend a _Stub.
        return self._name

    def GetProperty(self):
        return self._property

    def SetProperty(self, prop) -> None:
        self._property = prop
        # Mirror mounting axes + position onto the subsystem so per-emitter
        # spawn position and direction-gating consult the hardpoint values
        # rather than falling through to TGObject's stub catch-all.
        if prop is None:
            return
        if hasattr(prop, "GetPosition"):
            p = prop.GetPosition()
            if isinstance(p, TGPoint3):
                self._position = TGPoint3(p.x, p.y, p.z)
        if hasattr(prop, "GetDirection"):
            d = prop.GetDirection()
            if isinstance(d, TGPoint3):
                self._direction = TGPoint3(d.x, d.y, d.z)
        if hasattr(prop, "GetRight"):
            r = prop.GetRight()
            if isinstance(r, TGPoint3):
                self._right = TGPoint3(r.x, r.y, r.z)
        if hasattr(prop, "GetUp"):
            u = prop.GetUp()
            if isinstance(u, TGPoint3):
                self._up = TGPoint3(u.x, u.y, u.z)
        # hasattr is misleading on TGObject subclasses (fallback __getattr__
        # synthesizes Get* / Set* for any name and the synthesized getter
        # returns None when the key isn't set).  Only mirror when the return
        # value matches the expected shape.
        if hasattr(prop, "GetArcWidthAngles"):
            val = prop.GetArcWidthAngles()
            if isinstance(val, tuple) and len(val) == 2:
                self._arc_width_lo, self._arc_width_hi = float(val[0]), float(val[1])
                self._arc_set = True
        if hasattr(prop, "GetArcHeightAngles"):
            val = prop.GetArcHeightAngles()
            if isinstance(val, tuple) and len(val) == 2:
                self._arc_height_lo, self._arc_height_hi = float(val[0]), float(val[1])
                self._arc_set = True
        if hasattr(prop, "GetMaxDamage"):
            val = prop.GetMaxDamage()
            if isinstance(val, (int, float)):
                self._max_damage = float(val)
        if hasattr(prop, "GetMaxDamageDistance"):
            val = prop.GetMaxDamageDistance()
            if isinstance(val, (int, float)):
                self._max_damage_distance = float(val)
        if hasattr(prop, "GetDamageRadiusFactor"):
            val = prop.GetDamageRadiusFactor()
            if isinstance(val, (int, float)):
                self._damage_radius_factor = float(val)
        if hasattr(prop, "GetLength"):
            val = prop.GetLength()
            if isinstance(val, (int, float)):
                self._length = float(val)
        if hasattr(prop, "GetWidth"):
            val = prop.GetWidth()
            if isinstance(val, (int, float)):
                self._width = float(val)
        if hasattr(prop, "GetLengthTextureTilePerUnit"):
            val = prop.GetLengthTextureTilePerUnit()
            if isinstance(val, (int, float)):
                self._length_texture_tile_per_unit = float(val)
        # Phaser-specific fields.  The typed getters live on PhaserProperty
        # (not the EnergyWeaponProperty base) so isinstance-check by
        # return-value type — non-phaser properties' data-bag fallback
        # returns None.
        if hasattr(prop, "GetPhaserWidth"):
            v = prop.GetPhaserWidth()
            if isinstance(v, (int, float)): self._phaser_width = float(v)
        if hasattr(prop, "GetMainRadius"):
            v = prop.GetMainRadius()
            if isinstance(v, (int, float)): self._main_radius = float(v)
        if hasattr(prop, "GetCoreScale"):
            v = prop.GetCoreScale()
            if isinstance(v, (int, float)): self._core_scale = float(v)
        for getter, attr in (
            ("GetOuterShellColor", "_outer_shell_color"),
            ("GetInnerShellColor", "_inner_shell_color"),
            ("GetOuterCoreColor",  "_outer_core_color"),
            ("GetInnerCoreColor",  "_inner_core_color"),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, tuple) and len(v) == 4:
                    setattr(self, attr, v)
        if hasattr(prop, "GetTextureName"):
            v = prop.GetTextureName()
            if isinstance(v, str):
                self._texture_name = v
        for getter, attr in (
            ("GetNumSides",       "_num_sides"),
            ("GetTaperRadius",    "_taper_radius"),
            ("GetTaperRatio",     "_taper_ratio"),
            ("GetTaperMinLength", "_taper_min_length"),
            ("GetTaperMaxLength", "_taper_max_length"),
            ("GetPerimeterTile",  "_perimeter_tile"),
            ("GetTextureSpeed",   "_texture_speed"),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, (int, float)):
                    setattr(self, attr,
                             int(v) if attr == "_num_sides" else float(v))
        # WeaponsDisplay icon descriptor — typed on SubsystemProperty;
        # the data-bag stubs on bare TGObject return non-int garbage so
        # gate on isinstance to keep stubs from poisoning the mirror.
        for getter, attr, coerce in (
            ("GetIconNum",                  "_icon_num",                       int),
            ("GetIconPositionX",            "_icon_position_x_px",             float),
            ("GetIconPositionY",            "_icon_position_y_px",             float),
            ("IsIconAboveShip",             "_icon_above_ship",                int),
            ("GetIndicatorIconNum",         "_indicator_icon_num",             int),
            ("GetIndicatorIconPositionX",   "_indicator_icon_position_x_px",   float),
            ("GetIndicatorIconPositionY",   "_indicator_icon_position_y_px",   float),
        ):
            if hasattr(prop, getter):
                v = getattr(prop, getter)()
                if isinstance(v, (int, float)):
                    setattr(self, attr, coerce(v))
        # DamageDisplay placement — typed on SubsystemProperty,
        # returned as a (x, y) tuple. Same defensive isinstance gate as
        # the icon mirror above so data-bag stubs don't poison the value.
        if hasattr(prop, "GetPosition2D"):
            v = prop.GetPosition2D()
            if (isinstance(v, tuple) and len(v) == 2
                and all(isinstance(c, (int, float)) for c in v)):
                self._position_2d = (float(v[0]), float(v[1]))

    def IsTypeOf(self, cls) -> int:
        """SDK class-id check. Returns 1 when this subsystem's source
        property is an instance of `cls`, else 0.

        `cls` may be a fall-through stub (e.g. App.CT_UNKNOWN_THING
        returns an App._NamedStub instance), so guard with
        isinstance(cls, type) before testing.
        """
        if self._property is None or not isinstance(cls, type):
            return 0
        return 1 if isinstance(self._property, cls) else 0

    def GetParentShip(self):
        return self._parent_ship

    def SetParentShip(self, ship) -> None:
        self._parent_ship = ship

    def GetParentSubsystem(self):
        return self._parent_subsystem

    def GetChildSubsystem(self):
        return self._child_subsystem

    def GetCondition(self) -> float:
        return self._condition

    def SetCondition(self, value: float) -> None:
        """Floor at zero. DamageSystem (Task 4) routes hits through here."""
        self._condition = max(0.0, float(value))
        self._condition_changed()

    def GetMaxCondition(self) -> float:
        # The property template is the authoritative max-condition, mirroring
        # BC's C++ subsystems which delegate max to their property. This matters
        # when a mission mutates the max AFTER load via the property — e.g. E1M2
        # CreateDebris does pHull.GetProperty().SetMaxCondition(300) then
        # SetCondition(300) to peg an asteroid at full health. Properties are
        # SHARED templates (one per ship class), so per-ship current condition
        # stays in self._condition while the (per-class) max comes from here.
        prop = self._property
        if prop is not None:
            try:
                pm = prop.GetMaxCondition()
            except Exception:
                pm = None
            if pm is not None and float(pm) > 0.0:
                return float(pm)
        return self._max_condition

    def SetMaxCondition(self, value: float) -> None:
        # SDK App.py:5601 — also seed current condition when bumping max from
        # the default so freshly-loaded ships start undamaged.
        v = float(value)
        if self._condition == self._max_condition:
            self._condition = v
        self._max_condition = v
        self._condition_changed()

    def _condition_changed(self) -> None:
        """Push the fresh condition FRACTION into the combined watcher (if one
        was ever handed out) so its registered threshold crossings fire.
        Called from every _condition/_max_condition mutation path — all
        writes route through SetCondition/SetMaxCondition (combat damage in
        engine/appc/objects.py calls SetCondition)."""
        if self._combined_watcher is not None:
            self._combined_watcher._update(self.GetConditionPercentage())

    def GetConditionPercentage(self) -> float:
        mx = self.GetMaxCondition()
        if mx <= 0:
            return 0.0
        # Clamp: a mission may set condition above the (possibly lowered) max;
        # 100% is the ship's intended full health, never an overflowing bar.
        return max(0.0, min(1.0, self._condition / mx))

    def GetCombinedConditionPercentage(self) -> float:
        # SDK aggregates self + child subsystems; Phase 1 ships have no
        # children so this collapses to the same value.
        return self.GetConditionPercentage()

    def GetDamage(self) -> float:
        return max(0.0, self.GetMaxCondition() - self._condition)

    def GetRepairPointsNeeded(self) -> int:
        return int(max(0.0, self.GetMaxCondition() - self._condition))

    def GetRadius(self) -> float:
        return self._radius

    def SetRadius(self, value: float) -> None:
        self._radius = float(value)

    def GetPositionTG(self) -> TGPoint3:
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetPosition(self) -> TGPoint3:
        return self.GetPositionTG()

    def GetDirection(self) -> TGPoint3:
        return TGPoint3(self._direction.x, self._direction.y, self._direction.z)

    def SetDirection(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._direction = TGPoint3(v.x, v.y, v.z)

    def GetRight(self) -> TGPoint3:
        return TGPoint3(self._right.x, self._right.y, self._right.z)

    def SetRight(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._right = TGPoint3(v.x, v.y, v.z)

    def GetUp(self) -> TGPoint3:
        return TGPoint3(self._up.x, self._up.y, self._up.z)

    def SetUp(self, v) -> None:
        if isinstance(v, TGPoint3):
            self._up = TGPoint3(v.x, v.y, v.z)

    # Mirror BC's PhaserBank API names — sdk App.py:6478-6489.
    def GetOrientationForward(self) -> TGPoint3: return self.GetDirection()
    def GetOrientationUp(self)      -> TGPoint3: return self.GetUp()
    def GetOrientationRight(self)   -> TGPoint3: return self.GetRight()

    def GetArcWidthAngles(self) -> tuple:
        return (self._arc_width_lo, self._arc_width_hi)

    def GetArcHeightAngles(self) -> tuple:
        return (self._arc_height_lo, self._arc_height_hi)

    def GetMaxDamage(self) -> float:
        return self._max_damage

    def GetMaxDamageDistance(self) -> float:
        return self._max_damage_distance

    def GetDamageRadiusFactor(self) -> float:
        return self._damage_radius_factor

    def SetDamageRadiusFactor(self, v) -> None:
        self._damage_radius_factor = float(v)

    def GetLength(self) -> float:
        return self._length

    def GetWidth(self) -> float:
        return self._width

    def GetLengthTextureTilePerUnit(self) -> float:
        return self._length_texture_tile_per_unit

    # WeaponsDisplay icon descriptor — mirrored from SubsystemProperty.
    # Returns the SDK-faithful zero/0 defaults on subsystems without a
    # bound property so callers don't need to None-check before reading.
    def GetIconNum(self) -> int:                          return self._icon_num
    def GetIconPositionX(self) -> float:                  return self._icon_position_x_px
    def GetIconPositionY(self) -> float:                  return self._icon_position_y_px
    def IsIconAboveShip(self) -> int:                     return self._icon_above_ship
    def GetIndicatorIconNum(self) -> int:                 return self._indicator_icon_num
    def GetIndicatorIconPositionX(self) -> float:         return self._indicator_icon_position_x_px
    def GetIndicatorIconPositionY(self) -> float:         return self._indicator_icon_position_y_px

    def GetPosition2D(self) -> tuple:
        return self._position_2d

    # Phaser-specific accessors (return defaults on non-phaser subsystems).
    def GetPhaserWidth(self) -> float:        return self._phaser_width
    def GetMainRadius(self) -> float:         return self._main_radius
    def GetCoreScale(self) -> float:          return self._core_scale
    def GetOuterShellColor(self) -> tuple:    return self._outer_shell_color
    def GetInnerShellColor(self) -> tuple:    return self._inner_shell_color
    def GetOuterCoreColor(self) -> tuple:     return self._outer_core_color
    def GetInnerCoreColor(self) -> tuple:     return self._inner_core_color
    def GetTextureName(self) -> str:          return self._texture_name
    def GetNumSides(self) -> int:             return self._num_sides
    def GetTaperRadius(self) -> float:        return self._taper_radius
    def GetTaperRatio(self) -> float:         return self._taper_ratio
    def GetTaperMinLength(self) -> float:     return self._taper_min_length
    def GetTaperMaxLength(self) -> float:     return self._taper_max_length
    def GetPerimeterTile(self) -> float:      return self._perimeter_tile
    def GetTextureSpeed(self) -> float:       return self._texture_speed

    def GetWorldLocation(self) -> TGPoint3:
        # Direct attachment sets _parent_ship; child subsystems (pods/nacelles
        # added via AddChildSubsystem) only have _parent_subsystem, so climb the
        # chain to the ship. Without this, off-centre pods returned the bare
        # local mount near the origin — weapon aim at a locked nacelle fired
        # well off screen even though the reticle (which passes the ship
        # explicitly) located it correctly.
        ship = self._parent_ship
        if ship is None:
            ship = self._climb_to_ship()
        if ship is not None:
            return subsystem_world_position(self, ship)
        return self.GetPositionTG()

    def GetDamagePoint(self) -> TGPoint3:
        return self.GetPositionTG()

    def _climb_to_ship(self):
        """Walk parent-subsystem chain until a ShipClass is found.  Used
        by emitters that need their owning ship for world-space math."""
        # Direct attachment: ShipClass._attach_subsystem set _parent_ship.
        if self._parent_ship is not None:
            return self._parent_ship
        node = self.GetParentSubsystem()
        while node is not None:
            if hasattr(node, "GetParentShip") and node.GetParentShip() is not None:
                return node.GetParentShip()
            node = node.GetParentSubsystem() if hasattr(node, "GetParentSubsystem") else None
        return None

    def _emitter_world_position(self) -> TGPoint3:
        """World position of this emitter mount: ship_loc + R · local.
        Delegates to the module-level subsystem_world_position helper."""
        return subsystem_world_position(self)

    def _strip_emit_position(self, target_world) -> TGPoint3:
        """Closest point on a phaser-strip arc to ``target_world``.

        Galaxy / Sovereign / etc. phaser banks describe a curved strip,
        not a straight line: the rim lies on a sphere of radius
        ``Length`` around ``Position``, swept across ``ArcWidthAngles``
        around the ``Up`` axis. The beam emerges from whichever point on
        the arc is closest (in angular yaw) to the target.

        Algorithm (see research doc § "Strip emit point algorithm"):

        1. Rotate Position + Forward + Up into world space via the
           ship's body→world rotation.
        2. world_right = world_up × world_forward (right-handed; closes
           the basis used by the arc gate).
        3. Project (target - world_position) onto (forward, right).
        4. yaw = atan2(right_proj, fwd_proj).
        5. Clamp yaw to ``ArcWidthAngles``.
        6. Rodrigues-rotate ``world_forward`` around ``world_up`` by the
           clamped yaw to get the emit direction.
        7. emit = world_position + Length × emit_direction.

        Point emitters (``Length == 0``) collapse to
        ``_emitter_world_position()``.
        """
        center = self._emitter_world_position()
        length = self.GetLength() if hasattr(self, "GetLength") else 0.0
        if length <= 0.0:
            return center
        ship = self._climb_to_ship()
        if ship is None:
            return center
        rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
        if not isinstance(rot, TGMatrix3):
            return center

        # Body-frame basis rotated into world space.
        world_forward = TGPoint3(self._direction.x, self._direction.y, self._direction.z)
        world_forward.MultMatrixLeft(rot)
        world_up = TGPoint3(self._up.x, self._up.y, self._up.z)
        world_up.MultMatrixLeft(rot)
        # Right = forward × up. Under the right-handed convention (post
        # 2026-06-18 un-mirror) this is R·(forward×up) = R·GetCol(0) = true
        # starboard, matching the arc gate (_emitter_in_arc) so the beam
        # emerges on the same side the gate admits. See docs/superpowers/plans/
        # 2026-06-18-render-handedness-unmirror.md.
        world_right = TGPoint3(
            world_forward.y * world_up.z - world_forward.z * world_up.y,
            world_forward.z * world_up.x - world_forward.x * world_up.z,
            world_forward.x * world_up.y - world_forward.y * world_up.x,
        )

        # Project target offset onto the (forward, right) plane.
        dx = target_world.x - center.x
        dy = target_world.y - center.y
        dz = target_world.z - center.z
        fwd_proj   = dx * world_forward.x + dy * world_forward.y + dz * world_forward.z
        right_proj = dx * world_right.x   + dy * world_right.y   + dz * world_right.z

        # Yaw, clamped to the bank's horizontal arc.
        if fwd_proj == 0.0 and right_proj == 0.0:
            yaw = 0.0
        else:
            yaw = _math.atan2(right_proj, fwd_proj)
        yaw_lo = getattr(self, "_arc_width_lo", -_math.pi)
        yaw_hi = getattr(self, "_arc_width_hi",  _math.pi)
        yaw = max(yaw_lo, min(yaw_hi, yaw))

        # Rotate world_forward toward world_right by yaw, in their (orthonormal)
        # plane: emit = cos(yaw)·forward + sin(yaw)·right. Because yaw was
        # measured as atan2(right_proj, fwd_proj) against the SAME world_right,
        # a +yaw target gives an emit on the +right (target) side — the beam
        # faces the target. (Replaces the old up×forward Rodrigues, whose sin
        # term pointed along -world_right under the right-handed convention.)
        c, s = _math.cos(yaw), _math.sin(yaw)
        emit_dir = TGPoint3(
            world_forward.x * c + world_right.x * s,
            world_forward.y * c + world_right.y * s,
            world_forward.z * c + world_right.z * s,
        )

        return TGPoint3(
            center.x + emit_dir.x * length,
            center.y + emit_dir.y * length,
            center.z + emit_dir.z * length,
        )

    def GetNextTargetableChildSubsystem(self):
        return None

    def GetConditionWatcher(self):
        return None

    def GetCombinedPercentageWatcher(self):
        """FloatRangeWatcher on this subsystem's condition FRACTION
        (GetConditionPercentage). Lazily created, seeded with the current
        fraction so the first mutation is measured from real state.
        SDK consumer: pShip.GetHull().GetCombinedPercentageWatcher()
        (Bridge/Characters/Brex.py:108, EngineerCharacterHandlers.py) —
        but the base-class implementation serves ANY subsystem asked."""
        if self._combined_watcher is None:
            self._combined_watcher = FloatRangeWatcher(
                self.GetConditionPercentage())
        return self._combined_watcher

    # ── Child-subsystem walking ──────────────────────────────────────────────
    # SDK consumers iterate child subsystems via GetNumChildSubsystems +
    # GetChildSubsystem(i) (e.g. E2M2 PrepMarauder, E5M2 CreateGeronimo).
    # Hardpoints register TractorBeamProperty etc. as children of the parent
    # WeaponSystemProperty; SetupProperties Pass 4 materialises live children
    # from those property templates.

    def GetNumChildSubsystems(self) -> int:
        return len(self._children)

    def GetChildSubsystem(self, arg=None):
        if arg is None:
            return None
        if isinstance(arg, int):
            if 0 <= arg < len(self._children):
                return self._children[arg]
            return None
        if isinstance(arg, str):
            for c in self._children:
                if c.GetName() == arg:
                    return c
            return None
        return None

    def AddChildSubsystem(self, sub: "ShipSubsystem") -> None:
        sub._parent_subsystem = self
        self._children.append(sub)

    def GetCritical(self) -> int:                       return self._critical
    def SetCritical(self, v) -> None:                   self._critical = int(v)
    def GetTargetable(self) -> int:                     return self._targetable
    def SetTargetable(self, v) -> None:                 self._targetable = int(v)
    def GetPrimary(self) -> int:                        return self._primary
    def SetPrimary(self, v) -> None:                    self._primary = int(v)
    def GetDisabledPercentage(self) -> float:           return self._disabled_percentage
    def SetDisabledPercentage(self, v) -> None:         self._disabled_percentage = float(v)

    # ── Runtime predicates consumed by AI/Preprocessors.py ───────────────────
    # SDK App.py:5652-5657 — native methods on ShipSubsystem.  Phase 1 stubs
    # return SDK-faithful defaults; richer hooks (per-subsystem criticality
    # flags, LOS to subsystem position) land alongside the consumers that
    # need them.

    def IsCritical(self) -> int:
        """SDK Preprocessors.py:963 — true when destroying this subsystem
        destroys the ship.  Reflects the `_critical` flag set from hardpoint
        SubsystemProperty data via SetCritical (every hardpoint flags the
        hull and warp core critical).  The death sequence reads this to
        decide whether a zero-condition subsystem kills the ship."""
        return 1 if self._critical else 0

    def IsTargetable(self) -> int:
        """SDK Preprocessors.py:953-954, 829 — AI iterates subsystems and
        only adds those reporting IsTargetable()=1 to the rating list; the
        target-menu builder (RebuildShipMenu) likewise hides untargetable
        subsystems. The flag is copied from the hardpoint property in
        SetupProperties (SubsystemProperty.SetTargetable). An asteroid's
        Shield Generator / Power Plant set SetTargetable(0), so they never
        appear in the target list."""
        return 1 if self._targetable else 0

    def IsDisabled(self) -> int:
        """SDK Preprocessors.py:823, 974 — condition has fallen at or below
        DisabledPercentage × MaxCondition. Mirrors the same heuristic the
        rating loop applies via GetDisabledPercentage() / GetMaxCondition()
        / GetCondition(); kept consistent so callers and raters agree."""
        if self._max_condition <= 0.0:
            return 0
        threshold = self._disabled_percentage * self._max_condition
        return 1 if self._condition <= threshold else 0

    def IsDamaged(self) -> int:
        """Returns 1 if the subsystem has taken any damage (condition below
        max) or the explicit _damaged flag is set, 0 when fully healthy.

        Condition-based derivation: damaged = 0 < condition < max_condition.
        The explicit SetDamaged flag lets tests and the damage system
        force the state without touching condition fields."""
        if self._damaged:
            return 1
        if self._max_condition > 0.0 and 0.0 < self._condition < self._max_condition:
            return 1
        return 0

    def SetDamaged(self, value) -> None:
        """Explicitly mark this subsystem as damaged (or clear the flag)."""
        self._damaged = bool(value)

    def IsDestroyed(self) -> int:
        """Returns 1 if the subsystem is permanently destroyed (condition == 0)
        or the explicit _destroyed flag is set, 0 otherwise."""
        if self._destroyed:
            return 1
        if self._max_condition > 0.0 and self._condition <= 0.0:
            return 1
        return 0

    def SetDestroyed(self, value) -> None:
        """Explicitly mark this subsystem as destroyed (or clear the flag)."""
        self._destroyed = bool(value)

    def IsHittableFromLocation(self, vWorldLoc) -> float:
        """SDK Preprocessors.py:980 — `fHittable = pSubsystem.IsHittableFromLocation(pOurShip.GetWorldLocation())`.
        Native Appc returns a scalar (0.0..1.0) reflecting LOS / occlusion
        from the firing ship's location to the subsystem position. Phase 1
        treats every subsystem as fully hittable (no occlusion model);
        real geometry support lands when the renderer carries collision
        meshes."""
        return 1.0


# BC draw modes (ship-subsystems.md:164-189).  Per-class assignment below;
# tractor is deliberately mode 0 (manual/UI say Main; RE doc's mode-1 claim
# treated as mislabel — see spec "Decisions" §2).
PSM_MAIN_FIRST = 0
PSM_BACKUP_FIRST = 1
PSM_BACKUP_ONLY = 2


class PoweredSubsystem(ShipSubsystem):
    """Powered subsystem — consumes power, has a target power level."""

    POWER_MODE = PSM_MAIN_FIRST

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._normal_power = 0.0
        self._current_power = 0.0
        # On/off state — TurnOn/TurnOff drive gating in WeaponSystem.StartFiring
        # and the shield-raise pathway.  Default off matches the SDK; a fresh
        # ship is unpowered until ShipClass.SetAlertLevel(RED) or a mission
        # script explicitly turns systems on.
        self._is_on: bool = False
        self._power_percentage_wanted: float = 1.0   # BC spawns at 100%
        self._power_wanted: float = 0.0              # per-tick demand  (+0x8C)
        self._power_received: float = 0.0            # per-tick receipt (+0x88)
        self._efficiency: float = 1.0                # received/wanted  (+0x94)
        self._power_factor: float = 1.0              # received/(normal*dt) (+0x98)
        self._power_source = None

    def GetNormalPowerPerSecond(self) -> float:
        return self._normal_power

    def SetNormalPowerPerSecond(self, value: float) -> None:
        self._normal_power = float(value)

    def GetPowerPerSecond(self) -> float:
        return self._current_power

    def SetPowerPerSecond(self, value: float) -> None:
        self._current_power = float(value)

    def TurnOn(self) -> None:                              self._is_on = True
    def TurnOff(self) -> None:                             self._is_on = False
    def IsOn(self) -> int:                                 return 1 if self._is_on else 0

    def SetPowerPercentageWanted(self, pct) -> None:
        pct = float(pct)
        if pct < 0.0:
            pct = 0.0
        if pct > 1.25:
            pct = 1.25
        old = self._power_percentage_wanted
        self._power_percentage_wanted = pct
        # BC FUN_00562430: rescale current demand in place.
        if old != 0.0:
            self._power_wanted = self._power_wanted * pct / old
        self._fire("ET_SUBSYSTEM_POWER_CHANGED")

    def GetPowerPercentageWanted(self) -> float:           return self._power_percentage_wanted
    def GetPowerWanted(self) -> float:                     return self._power_wanted
    def SetPowerWanted(self, v) -> None:                   self._power_wanted = float(v)
    def GetNormalPowerWanted(self) -> float:               return self._normal_power
    def GetPowerReceived(self) -> float:                   return self._power_received
    def GetPowerPercentage(self) -> float:                 return self._efficiency
    def GetNormalPowerPercentage(self) -> float:           return self._power_factor
    def SetPowerSource(self, src) -> None:                 self._power_source = src

    def Turn(self, on) -> None:
        if on:
            self.TurnOn()
        else:
            self.TurnOff()

    def _wants_power(self) -> bool:
        return bool(self._is_on)

    # ── Subsystem event emission ─────────────────────────────────────────────

    def _fire(self, event_attr: str) -> None:
        """Broadcast a subsystem event with the owning ship as both source AND
        destination — mirrors ship_death._broadcast_destroyed.  Raise-safe so
        a missing event manager never breaks the state machine.

        The destination MUST be the ship: target-scoped method handlers
        (Preprocessors.py) only fire when ``event.GetDestination() is pTarget``.
        Falls back to ``self`` for a parentless subsystem (unit fixtures)."""
        try:
            import App
            ship = self.GetParentShip() if hasattr(self, "GetParentShip") else None
            owner = ship if ship is not None else self
            evt = App.TGEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(owner)
            evt.SetDestination(owner)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("subsystem event broadcast", _e)


class HullSubsystem(ShipSubsystem):
    """Live hull state.  Hull isn't a powered subsystem — it just tracks
    condition (max + current) so damage logic can read GetMaxCondition().

    The hull is critical by nature: every ship hardpoint sets
    ``Hull.SetCritical(1)``, and a ship whose hull reaches zero is
    destroyed.  Default ``_critical = 1`` so even a hull built without the
    hardpoint property flow (tests, minimally-constructed ships) still
    triggers the death sequence on hull-zero.  The property flow may
    re-assert this via SetCritical, but never clears it (no hardpoint
    flags the hull non-critical)."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._critical = 1


class SensorSubsystem(PoweredSubsystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        # Sensors are ON during normal operation — unlike weapons (powered only
        # at RED alert) a functioning sensor array is always running; BC only
        # reports IsOn()==0 when the subsystem is destroyed/disabled. The base
        # PoweredSubsystem defaults _is_on False (right for weapons), so override
        # it here. Without this, SDK gates that check pSensors.IsOn() short-
        # circuit: e.g. E1M2's ScanHandler bails to the generic "Scan Area"
        # acknowledgement instead of running the mission scan (nothing in the
        # engine's ship-power path ever turned sensors on).
        self._is_on: bool = True
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0
        # Objects whose existence is known to the sensor system.
        # Populated by the game loop / radar sweep logic.  Default is
        # empty (nothing known), matching the initial unscanned state.
        self._known_objects: set = set()

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)

    def IsObjectKnown(self, obj) -> int:
        """Returns 1 if *obj* is in the known-contacts set, 0 otherwise.

        The SDK ShieldsDisplay.SetShipIcon gate (line 329-338) checks this
        before showing a target panel — unknown contacts render no data.
        """
        try:
            return 1 if obj.GetObjID() in self._known_objects else 0
        except Exception:
            return 0

    def AddKnownObject(self, obj) -> None:
        """Register *obj* as a known sensor contact."""
        try:
            self._known_objects.add(obj.GetObjID())
        except Exception as _e:
            dev_mode.log_swallowed("AddKnownObject", _e)

    def RemoveKnownObject(self, obj) -> None:
        """Remove *obj* from known contacts."""
        try:
            self._known_objects.discard(obj.GetObjID())
        except Exception as _e:
            dev_mode.log_swallowed("RemoveKnownObject", _e)

    def ScanAllObjects(self):
        """Active area scan (Science menu "Scan Area").

        The SDK's ``ScienceMenuHandlers.Scan`` and ``E1M2.ScanComplete`` do
        ``pSeq = pSensors.ScanAllObjects(); pSeq.Play()`` — E1M2 with no None
        guard — so this must ALWAYS return a real, playable ``TGSequence``.

        The sequence carries a single script action that, when played, identifies
        every contact in the scanning ship's set (see
        ``sensor_identification.identify_all_in_set``). Deferring the work into
        the played action matches the SDK contract that playing the sequence *is*
        the scan; it also de-dupes against the passive per-tick sweep."""
        import App
        seq = App.TGSequence_Create()
        ship = self.GetParentShip()
        if ship is None and hasattr(self, "_climb_to_ship"):
            ship = self._climb_to_ship()
        if ship is not None:
            try:
                action = App.TGScriptAction_Create(
                    "engine.appc.sensor_identification",
                    "ScanAllObjectsAction", ship.GetObjID())
                seq.AddAction(action)
            except Exception as _e:
                dev_mode.log_swallowed("ScanAllObjects build", _e)
        return seq

    def IdentifyObject(self, pTarget) -> None:
        """Single-target scan (Science menu "Scan Object" via
        ``Actions.ShipScriptActions.ScanObject``): mark *pTarget* known and
        broadcast ``ET_SENSORS_SHIP_IDENTIFIED`` once. De-duped, so re-scanning
        an already-known contact is a no-op."""
        from engine.appc import sensor_identification
        sensor_identification._identify_one(self, pTarget)

    def ForceObjectIdentified(self, pTarget) -> None:
        """SDK ``HelmMenuHandlers.SetupOrbitMenuFromSet`` marks orbitable
        planets identified so the player can target them (all planets are
        automatically targetable). Reuses the sensor-identification store;
        None-safe and de-duped (a no-op if *pTarget* is None or already known)."""
        from engine.appc import sensor_identification
        sensor_identification._identify_one(self, pTarget)


class ImpulseEngineSubsystem(PoweredSubsystem):
    """Live impulse-engine state.  Speed/accel limits come from the
    matching ImpulseEngineProperty template via ShipClass.SetupProperties()."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Engines run from spawn — same rationale as SensorSubsystem above:
        # the PoweredSubsystem off/0.0 default is right for weapons (RED-alert
        # powered), but BC ships fly under engine power from creation, and SDK
        # gates read that state: HelmCharacterHandlers.OrbitPlanet and
        # {Helm,}MenuHandlers.SetCourse divert to the XO "need power to
        # engines" warning when GetPowerPercentageWanted() == 0.0, and
        # WarpPressed blocks warp when the warp engines are not IsOn()
        # (currently deferred in warp_gates for exactly this false-positive).
        self._is_on = True
        self._power_percentage_wanted = 1.0
        self._max_speed = 0.0
        self._max_accel = 0.0
        self._max_angular_velocity = 0.0
        self._max_angular_accel = 0.0

    def GetMaxSpeed(self) -> float:           return self._max_speed
    def SetMaxSpeed(self, v: float) -> None:  self._max_speed = float(v)
    def GetMaxAccel(self) -> float:           return self._max_accel
    def SetMaxAccel(self, v: float) -> None:  self._max_accel = float(v)
    def GetMaxAngularVelocity(self) -> float: return self._max_angular_velocity
    def SetMaxAngularVelocity(self, v: float) -> None:
        self._max_angular_velocity = float(v)
    def GetMaxAngularAccel(self) -> float:    return self._max_angular_accel
    def SetMaxAngularAccel(self, v: float) -> None:
        self._max_angular_accel = float(v)


class WarpEngineSubsystem(PoweredSubsystem):
    # Warp-state constants from sdk/.../App.py:6700-6707.
    # SDK consumers: WarpSequence.py, mission scripts checking warp transitions.
    WES_NOT_WARPING       = 0
    WES_WARP_INITIATED    = 1
    WES_WARP_BEGINNING    = 2
    WES_WARP_ENDING       = 3
    WES_WARPING           = 4
    WES_DEWARP_INITIATED  = 5
    WES_DEWARP_BEGINNING  = 6
    WES_DEWARP_ENDING     = 7

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Powered from spawn, like ImpulseEngineSubsystem — see the comment
        # there (SDK engines-off gates false-positive on the weapons default).
        self._is_on = True
        self._power_percentage_wanted = 1.0
        self._warp_sequence = None
        self._warp_effect_time = 0.0
        self._warp_state = self.WES_NOT_WARPING

    def GetWarpSequence(self):
        return self._warp_sequence

    def SetWarpSequence(self, seq) -> None:
        self._warp_sequence = seq

    def GetWarpEffectTime(self) -> float:
        return self._warp_effect_time

    def SetWarpEffectTime(self, t: float) -> None:
        self._warp_effect_time = float(t)

    def GetWarpState(self) -> int:
        return self._warp_state

    def SetWarpState(self, state) -> None:
        self._warp_state = int(state)


class ShieldSubsystem(PoweredSubsystem):
    """Six-face shield generator.

    Faces indexed by ShieldProperty.FRONT_SHIELDS..RIGHT_SHIELDS (0..5).
    SetMaxShields seeds current to that max when current was 0 — mirrors
    HullSubsystem.SetMaxCondition so freshly-loaded ships start fully shielded.
    """
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields:       list[float] = [0.0] * self.NUM_SHIELDS
        self._current_shields:   list[float] = [0.0] * self.NUM_SHIELDS
        self._charge_per_second: list[float] = [0.0] * self.NUM_SHIELDS
        # FloatRangeWatchers handed to SDK consumers. Indices 0..5 are the
        # per-face watchers (Conditions/ConditionSingleShieldBelow.py:110,
        # GetShieldWatcher(side)), each watching its face FRACTION
        # (current / max). Index 6 (NUM_SHIELDS) is BC's COMBINED/overall
        # shields watcher (Bridge/Characters/Brex.py:107 GetShieldWatcher(6)),
        # watching GetShieldPercentage(). All driven from SetCurrentShields
        # and Update.
        self._shield_watchers: list = [
            FloatRangeWatcher() for _ in range(self.NUM_SHIELDS + 1)
        ]

    def GetShieldWatcher(self, face: int):
        """FloatRangeWatcher on a face's FRACTION for faces 0..5
        (Conditions/ConditionSingleShieldBelow.py:110, eWhichShield);
        index 6 (NUM_SHIELDS) is the COMBINED shields watcher on
        GetShieldPercentage() (Bridge/Characters/Brex.py:107)."""
        return self._shield_watchers[int(face)]

    def GetCombinedPercentageWatcher(self):
        """The COMBINED shields watcher — same object as GetShieldWatcher(6).
        SDK consumer: EngineerCharacterHandlers hull/shield status parity."""
        return self._shield_watchers[self.NUM_SHIELDS]

    def HasShields(self) -> int:
        """True only when at least one face has real shield capacity.

        Unshielded hulls (e.g. asteroids, whose ShieldProperty declares all six
        faces at MaxShields=0) still get a ShieldSubsystem so SDK code can chain
        GetShields() without null-guarding, but they have no actual shields. The
        target list uses this to suppress the shield bar rather than showing the
        100% that GetShieldPercentage() reports for a zero-max shield (that 1.0
        is deliberate — it tells the AI 'shields are not a factor here')."""
        return 1 if sum(self._max_shields) > 0.0 else 0

    def GetMaxShields(self, face: int) -> float:
        return self._max_shields[int(face)]

    def SetMaxShields(self, face: int, value: float) -> None:
        f = int(face)
        v = float(value)
        if self._current_shields[f] == 0.0:
            self._current_shields[f] = v
        self._max_shields[f] = v

    def GetCurrentShields(self, face: int) -> float:
        return self._current_shields[int(face)]

    def SetCurrentShields(self, face: int, value: float) -> None:
        f = int(face)
        self._current_shields[f] = float(value)
        # Keep the face watcher's value fresh so a Condition reading
        # GetWatchedVariable() right after a damage write sees the new
        # fraction (ConditionSingleShieldBelow.py:122 reads it at setup).
        self._shield_watchers[f]._update(self.GetSingleShieldPercentage(f))
        # The combined watcher tracks the same mutation.
        self._shield_watchers[self.NUM_SHIELDS]._update(
            self.GetShieldPercentage())

    def SetCurShields(self, face: int, value: float) -> None:
        """SDK-facing alias of SetCurrentShields (matches Appc method name)."""
        self.SetCurrentShields(face, value)

    def GetCurShields(self, face: int) -> float:
        """SDK-facing alias of GetCurrentShields (matches Appc method name).

        Used by SDK PlainAI/IntelligentCircleObject.py:176-179 for
        shield-bias orbit positioning."""
        return self.GetCurrentShields(face)

    def GetSingleShieldPercentage(self, face: int) -> float:
        """current/max for the face; 0.0 when max==0 (unshielded face).

        SDK caller MissionLib.IsAnyShieldBreached treats anything <0.05 as
        a breach, so the max==0 case must return 0.0, not raise.
        """
        f = int(face)
        mx = self._max_shields[f]
        if mx == 0.0:
            return 0.0
        return self._current_shields[f] / mx

    def GetShieldPercentage(self) -> float:
        """Aggregate ratio of total current shields to total max,
        across all 6 faces. Returns 1.0 when no face has max set
        (unshielded ship) so SelectTarget rating treats them as
        "shields not a factor" rather than "shields critically low."""
        total_max = sum(self._max_shields)
        if total_max <= 0:
            return 1.0
        total_cur = sum(self._current_shields)
        return total_cur / total_max

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)

    def Update(self, dt: float) -> None:
        """Per-tick regen: current += charge_per_second * dt, clamped to max.

        Faces with max==0 are skipped so unshielded faces never accumulate.

        Disabled-generator gate (Project 5 §4.4): when _is_offline(self),
        skip the whole loop. _charge_per_second values are NOT mutated;
        repair restores regen at the original rates on the next call.

        Powered-down gate: when the generator is not IsOn (alert level
        is GREEN, or nothing has raised shields yet), regen is suppressed.
        ShipClass.SetAlertLevel drains the face values to zero on the same
        transition; this gate just prevents Update from leaking charge
        back in.
        """
        if _is_offline(self):
            return
        if not self.IsOn():
            return
        # Cloak gate: while the ship is cloaked or mid-cloak its shields are
        # down (BC drops shields on cloak), so suppress regen — StartCloaking
        # already zeroed the faces; this keeps them collapsed until decloak.
        ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
        if ship is not None:
            cloak = (ship.GetCloakingSubsystem()
                     if hasattr(ship, "GetCloakingSubsystem") else None)
            if cloak is not None and cloak.IsTryingToCloak():
                return
        dt = float(dt)
        for f in range(self.NUM_SHIELDS):
            mx = self._max_shields[f]
            if mx == 0.0:
                continue
            new = self._current_shields[f] + self._charge_per_second[f] * dt
            if new > mx:
                new = mx
            self._current_shields[f] = new
        # Drive each face watcher with its FRACTION so
        # Conditions/ConditionSingleShieldBelow.py fires its
        # ET_AI_SHIELD_WATCHER crossing event; the combined watcher (index
        # NUM_SHIELDS) follows with the overall fraction — this is also where
        # both catch up after direct ApplyDamage face mutations.
        for f in range(self.NUM_SHIELDS):
            self._shield_watchers[f]._update(self.GetSingleShieldPercentage(f))
        self._shield_watchers[self.NUM_SHIELDS]._update(
            self.GetShieldPercentage())

    def ApplyDamage(self, face: int, amount: float) -> float:
        """Drain current shields on the face; return damage overflow.

        Caller routes the returned overflow to hull. Does not trigger
        regen, fire events, or mutate any other face.
        """
        f = int(face)
        amt = float(amount)
        cur = self._current_shields[f]
        if amt <= cur:
            self._current_shields[f] = cur - amt
            return 0.0
        self._current_shields[f] = 0.0
        return amt - cur


class PowerSubsystem(ShipSubsystem):
    """Power plant — drives the ship's energy budget.

    Inherits ShipSubsystem (not PoweredSubsystem) to match SDK
    App.py:5710 where PowerSubsystem inherits ShipSubsystem directly.
    It generates power rather than consuming it.

    Three pools mirror Appc (App.py:5739-5754):

    * **available** — instantaneous surplus from generation, refilled
      each tick.  Weapons drain this first.
    * **main battery** — capped reserve (PowerProperty.MainBatteryLimit)
      that absorbs surplus and surrenders it when available runs out.
    * **backup battery** — emergency reserve drained only via
      StealPowerFromReserve (backup-only path).

    StealPower / StealPowerFromReserve return the float amount actually
    taken (partial drain semantics, reservoir-specific).  0.0 is falsy
    so callers in weapon_subsystems.py that test ``if ps.StealPower(cost)``
    still work correctly.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._available_power: float = 0.0
        self._main_battery_power: float = 0.0
        self._backup_battery_power: float = 0.0
        # Conduit / interval tracking (Task 2: battery/conduit surface).
        self._main_conduit_current: float = 0.0
        self._backup_conduit_current: float = 0.0
        self._interval_elapsed: float = 0.0
        self._power_dispensed: float = 0.0
        self._power_wanted_total: float = 0.0
        # FloatRangeWatchers handed to Conditions/ConditionPowerBelow.py:44-46;
        # each watches its battery FRACTION (power / limit), driven from Update.
        self._main_battery_watcher = FloatRangeWatcher()
        self._backup_battery_watcher = FloatRangeWatcher()

    def GetAvailablePower(self) -> float:           return self._available_power
    def SetAvailablePower(self, v) -> None:         self._available_power = float(v)
    def GetMainBatteryPower(self) -> float:         return self._main_battery_power
    def SetMainBatteryPower(self, v) -> None:       self._main_battery_power = float(v)
    def GetBackupBatteryPower(self) -> float:       return self._backup_battery_power
    def SetBackupBatteryPower(self, v) -> None:     self._backup_battery_power = float(v)

    def SetProperty(self, prop) -> None:
        """Override to fill batteries to their limits on bind (BC FUN_005636D0).

        Ships spawn with batteries full so they can fire / shield before the
        first per-tick refill.  Delegates the rest of the property-mirror work
        to the ShipSubsystem base implementation."""
        super().SetProperty(prop)
        if prop is not None:
            self._main_battery_power = float(prop.GetMainBatteryLimit() or 0.0)
            self._backup_battery_power = float(prop.GetBackupBatteryLimit() or 0.0)

    def _prop_f(self, getter_name: str) -> float:
        """Read a float from the PowerProperty; returns 0.0 when no property
        is bound or the getter returns None (unset data-bag key)."""
        prop = self.GetProperty()
        if prop is None:
            return 0.0
        return float(getattr(prop, getter_name)() or 0.0)

    def GetMainBatteryLimit(self) -> float:
        """Main-battery cap from the PowerProperty (App.py:5743).

        ConditionPowerBelow.py:79 divides GetMainBatteryPower() by this to
        seed its initial state; 0.0 when no property is wired."""
        return self._prop_f("GetMainBatteryLimit")

    def GetBackupBatteryLimit(self) -> float:
        """Backup-battery cap from the PowerProperty (App.py:5744).

        Used by ConditionPowerBelow.py:77 for the reserve-only initial state."""
        return self._prop_f("GetBackupBatteryLimit")

    def GetPowerOutput(self) -> float:
        """Rated output scaled by condition (BC health-scaling asymmetry).

        The EPS plant delivers less power when damaged — scaled by
        GetConditionPercentage() just like GetMainConduitCapacity."""
        return self._prop_f("GetPowerOutput") * self.GetConditionPercentage()

    def GetMaxMainConduitCapacity(self) -> float:
        """Raw (undamaged) main conduit capacity from the PowerProperty."""
        return self._prop_f("GetMainConduitCapacity")

    def GetMainConduitCapacity(self) -> float:
        """Health-scaled main conduit capacity (BC asymmetry: main scales,
        backup does not)."""
        return self._prop_f("GetMainConduitCapacity") * self.GetConditionPercentage()

    def GetBackupConduitCapacity(self) -> float:
        """Backup conduit capacity — deliberately NOT health-scaled (BC asymmetry).

        The backup EPS path is hardened; it maintains its rated throughput
        even when the warp core is damaged."""
        return self._prop_f("GetBackupConduitCapacity")

    def GetPowerDispensed(self) -> float:
        """Total power dispensed to consumers this tick (filled by Task 4)."""
        return self._power_dispensed

    def GetPowerWanted(self) -> float:
        """Sum of power wanted by all consumers this tick (filled by Task 4)."""
        return self._power_wanted_total

    def GetMainBatteryWatcher(self):
        """FloatRangeWatcher on the main-battery FRACTION
        (Conditions/ConditionPowerBelow.py:46)."""
        return self._main_battery_watcher

    def GetBackupBatteryWatcher(self):
        """FloatRangeWatcher on the backup-battery FRACTION
        (Conditions/ConditionPowerBelow.py:44, bReserveOnly path)."""
        return self._backup_battery_watcher

    def AddPower(self, amount) -> None:
        self._available_power += float(amount)

    def DeductPower(self, amount) -> int:
        amt = float(amount)
        if amt > self._available_power:
            return 0
        self._available_power -= amt
        return 1

    def StealPower(self, amount) -> float:
        """Drain up to `amount` from the main battery; return the float amount
        actually taken.  Main-battery-only — does not touch available or backup.

        Returns 0.0 when the main battery is empty (falsy, matches caller
        boolean checks in weapon_subsystems.py).  Partial steals return the
        amount taken (truthy) so the caller can act on whatever was available.
        Task 4 will replace these call sites with a full conduit/allocation
        model; this bridge form keeps the API surface live."""
        take = min(float(amount), self._main_battery_power)
        self._main_battery_power -= take
        return take

    def StealPowerFromReserve(self, amount) -> float:
        """Drain up to `amount` from the backup battery; return the float
        amount actually taken.  Backup-battery-only — does not touch available
        or main.  0.0 return is falsy; positive return is truthy."""
        take = min(float(amount), self._backup_battery_power)
        self._backup_battery_power -= take
        return take

    # ── Per-tick flow ─────────────────────────────────────────────────────
    # BC uses a 1-second interval tick (FUN_005636D0 / 0x892E20 constant).
    # Elapsed game-time accumulates each call; when it crosses POWER_INTERVAL
    # the reactor fires: generate output*elapsed into batteries (main first,
    # spill to backup, discard), then compute conduit budgets from the new
    # battery levels and health-scaled capacity.  Between intervals the conduit
    # budgets are unchanged; the watcher fractions are updated every call so
    # the FloatRangeWatcher fires promptly on StealPower drains between ticks.

    POWER_INTERVAL: float = 1.0   # seconds of game time; BC constant 0x892E20

    _IDLE_DRAIN_SLOTS = (
        "GetSensorSubsystem", "GetImpulseEngineSubsystem",
        "GetWarpEngineSubsystem", "GetShieldSubsystem",
        "GetPhaserSystem", "GetTorpedoSystem",
        "GetPulseWeaponSystem", "GetTractorBeamSystem",
        "GetRepairSubsystem",
    )

    def _compute_idle_drain(self) -> float:
        # NOTE: _compute_idle_drain is present but unused after the Task 3
        # interval-tick rewrite; Task 4's consumer pump will replace it.
        ship = self.GetParentShip()
        if ship is None:
            return 0.0
        total = 0.0
        for getter_name in self._IDLE_DRAIN_SLOTS:
            getter = getattr(ship, getter_name, None)
            if getter is None:
                continue
            sub = getter()
            if sub is None:
                continue
            if not hasattr(sub, "IsOn") or not sub.IsOn():
                continue
            if not hasattr(sub, "GetNormalPowerPerSecond"):
                continue
            total += float(sub.GetNormalPowerPerSecond() or 0.0)

        # Cloak is metered separately: it draws its NormalPowerPerSecond only
        # while the ship is trying to stay hidden (CLOAKING or CLOAKED), not on
        # the PoweredSubsystem on/off flag.  BC drains the cloak for the whole
        # duration the device is engaged (warbird authors 1000 power/sec).
        cloak_getter = getattr(ship, "GetCloakingSubsystem", None)
        if cloak_getter is not None:
            cloak = cloak_getter()
            if (cloak is not None
                    and hasattr(cloak, "IsTryingToCloak")
                    and cloak.IsTryingToCloak()
                    and hasattr(cloak, "GetNormalPowerPerSecond")):
                total += float(cloak.GetNormalPowerPerSecond() or 0.0)
        return total

    def _add_power_to_batteries(self, amount: float) -> None:
        """Main first (capped), spill to backup (capped), discard the rest."""
        main_cap = self.GetMainBatteryLimit()
        backup_cap = self.GetBackupBatteryLimit()
        room = main_cap - self._main_battery_power
        take = min(amount, max(room, 0.0))
        self._main_battery_power += take
        spill = amount - take
        room = backup_cap - self._backup_battery_power
        self._backup_battery_power += min(spill, max(room, 0.0))

    def Update(self, dt: float) -> None:
        prop = self.GetProperty()
        if prop is None:
            return
        dt = float(dt)
        self._interval_elapsed += dt
        if self._interval_elapsed >= self.POWER_INTERVAL:
            elapsed = self._interval_elapsed
            self._interval_elapsed = 0.0
            self._power_dispensed = 0.0
            if not _is_offline(self):
                self._add_power_to_batteries(self.GetPowerOutput() * elapsed)
            main_max = self.GetMainConduitCapacity() * elapsed
            backup_max = self.GetBackupConduitCapacity() * elapsed
            self._main_conduit_current = min(self._main_battery_power, main_max)
            self._backup_conduit_current = min(self._backup_battery_power, backup_max)
            self._available_power = (self._main_conduit_current
                                     + self._backup_conduit_current)
        self._pump_consumers(dt)     # Task 4 fills this in
        main_cap = self.GetMainBatteryLimit()
        backup_cap = self.GetBackupBatteryLimit()
        # Drive the FloatRangeWatchers with each battery's FRACTION so
        # Conditions/ConditionPowerBelow.py fires its ET_POWER_FRACTION_CHANGED
        # crossing event (guard divide-by-zero → 0.0).
        self._main_battery_watcher._update(
            self._main_battery_power / main_cap if main_cap > 0.0 else 0.0
        )
        self._backup_battery_watcher._update(
            self._backup_battery_power / backup_cap if backup_cap > 0.0 else 0.0
        )

    def _pump_consumers(self, dt: float) -> None:
        pass   # Task 4


class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem.  SDK App.py:6639 has
    RepairSubsystem(PoweredSubsystem) with internal repair-allocation
    state; Phase 1 ships only need the slot + property back-ref so the
    targets panel reflects the hardpoint."""
    pass


# Default cloak/decloak transition length in seconds.  W5.T2 will overwrite
# the per-instance ``_transition_duration`` from the CloakingSubsystemProperty
# (CloakStrength); this module constant is the fallback for tests and ships
# built without the hardpoint property flow.
CLOAK_TRANSITION_DURATION: float = 4.5


class CloakingSubsystem(PoweredSubsystem):
    """Cloaking device — the four-state cloak/decloak transition machine.

    Driven entirely through the method surface the SDK CloakShip preprocessor
    relies on (sdk/Build/scripts/AI/Preprocessors.py:2068, CheckCloak; also the
    FedAttack / NonFedAttack / CloakAttack doctrines and the CloakShip
    preprocessor):

        pCloak = pOurShip.GetCloakingSubsystem()
        if self.bCloakOn:
            if (not pCloak.IsCloaked()) and (not pCloak.IsCloaking()):
                pCloak.StartCloaking()
        else:
            if pCloak.IsCloaked():
                pCloak.StopCloaking()

    States:

    * ``CLOAK_DECLOAKED``  — fully visible (initial state).
    * ``CLOAK_CLOAKING``   — fading out; transition in progress.
    * ``CLOAK_CLOAKED``    — fully invisible.
    * ``CLOAK_DECLOAKING`` — fading back in; transition in progress.

    The transition timer (``_transition_elapsed``) is advanced from the
    per-tick ``Update(dt)`` (the same hook ShieldSubsystem / PowerSubsystem use,
    walked from the game loop's subsystem update pass).  On crossing
    ``_transition_duration`` the machine snaps to CLOAKED / DECLOAKED and
    broadcasts the matching completion event (ET_CLOAK_COMPLETED /
    ET_DECLOAK_COMPLETED) via ``App.g_kEventManager`` — the same emission path
    used by ship_death._broadcast_destroyed.

    A disabled / destroyed cloaking device (PoweredSubsystem.IsDisabled() /
    IsDestroyed()) cannot hold or finish a cloak: while disabled it is forced
    back toward DECLOAKED rather than completing a pending cloak.  Logic only —
    the renderer hologram/fade VFX is out of scope for this task.
    """

    CLOAK_DECLOAKED  = 0
    CLOAK_CLOAKING   = 1
    CLOAK_CLOAKED    = 2
    CLOAK_DECLOAKING = 3

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._cloak_state: int = self.CLOAK_DECLOAKED
        self._transition_elapsed: float = 0.0
        # Per-instance so W5.T2 can set it from CloakStrength; defaults to the
        # module constant.
        self._transition_duration: float = CLOAK_TRANSITION_DURATION

    # ── Intent (called by the SDK CloakShip preprocessor) ────────────────────

    def StartCloaking(self) -> None:
        """Begin cloaking.  No-op if already CLOAKED or CLOAKING; from
        DECLOAKED or mid-DECLOAKING this (re)starts the fade-out and broadcasts
        ET_CLOAK_BEGINNING (BC fires the BEGINNING event at transition start —
        Bridge/PowerDisplay.py:340, E2M0/E2M1)."""
        if self._cloak_state in (self.CLOAK_CLOAKED, self.CLOAK_CLOAKING):
            return
        self._cloak_state = self.CLOAK_CLOAKING
        self._transition_elapsed = 0.0
        self._fire("ET_CLOAK_BEGINNING")
        self._play_cloak_sfx("Cloak")
        self._collapse_shields()
        self._stop_weapons()

    def StopCloaking(self) -> None:
        """Begin decloaking.  No-op if already DECLOAKED or DECLOAKING; from
        CLOAKED or mid-CLOAKING this (re)starts the fade-in and broadcasts
        ET_DECLOAK_BEGINNING (SelectTarget re-rates the contact on this event —
        Preprocessors.py)."""
        if self._cloak_state in (self.CLOAK_DECLOAKED, self.CLOAK_DECLOAKING):
            return
        self._cloak_state = self.CLOAK_DECLOAKING
        self._transition_elapsed = 0.0
        self._fire("ET_DECLOAK_BEGINNING")
        self._play_cloak_sfx("Uncloak")

    def InstantCloak(self) -> None:
        """Jump straight to CLOAKED with no transition; fire ET_CLOAK_COMPLETED.
        No BEGINNING event — there is no transition to begin (matches BC)."""
        self._cloak_state = self.CLOAK_CLOAKED
        self._transition_elapsed = 0.0
        self._fire("ET_CLOAK_COMPLETED")

    def InstantDecloak(self) -> None:
        """Jump straight to DECLOAKED with no transition; fire ET_DECLOAK_COMPLETED."""
        self._cloak_state = self.CLOAK_DECLOAKED
        self._transition_elapsed = 0.0
        self._fire("ET_DECLOAK_COMPLETED")

    # ── State predicates (read by CloakShip.CheckCloak + doctrines) ──────────

    def IsCloaked(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_CLOAKED else 0

    def IsCloaking(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_CLOAKING else 0

    def IsDecloaking(self) -> int:
        return 1 if self._cloak_state == self.CLOAK_DECLOAKING else 0

    def IsTryingToCloak(self) -> int:
        """True whenever the cloak is "on" — i.e. the intent is to be cloaked.
        That is CLOAKING (fading out toward cloaked) or already CLOAKED.
        DECLOAKING / DECLOAKED both express the intent to be visible."""
        return 1 if self._cloak_state in (self.CLOAK_CLOAKING,
                                          self.CLOAK_CLOAKED) else 0

    def GetTransitionFraction(self) -> float:
        """Visual cloak progress in [0, 1]: 0 = fully visible (DECLOAKED),
        1 = fully hidden (CLOAKED).  Ramps with the transition timer during
        CLOAKING (0→1) and back down during DECLOAKING (1→0).  The renderer
        drives the refraction / chromatic-dispersion strength off this — it is a
        pure read of the state machine and has no gameplay effect."""
        if self._cloak_state == self.CLOAK_DECLOAKED:
            return 0.0
        if self._cloak_state == self.CLOAK_CLOAKED:
            return 1.0
        dur = self._transition_duration if self._transition_duration > 0.0 else 1.0
        f = self._transition_elapsed / dur
        f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
        return f if self._cloak_state == self.CLOAK_CLOAKING else (1.0 - f)

    # ── Per-tick transition advance (game-loop subsystem update pass) ────────

    def Update(self, dt: float) -> None:
        """Advance an in-progress cloak/decloak transition.

        A disabled / destroyed device cannot complete or hold a cloak: when
        offline it is forced back toward DECLOAKED (a pending CLOAKING is
        abandoned, a finished CLOAKED snaps off).  Otherwise, when the elapsed
        transition time reaches ``_transition_duration`` the machine snaps to
        the terminal state and broadcasts its completion event.
        """
        offline = bool(self.IsDisabled()) or bool(self.IsDestroyed())
        if offline:
            # Forced decloak: a disabled cloak cannot keep the ship hidden.
            if self._cloak_state in (self.CLOAK_CLOAKING, self.CLOAK_CLOAKED):
                was_cloaked = self._cloak_state == self.CLOAK_CLOAKED
                self._cloak_state = self.CLOAK_DECLOAKED
                self._transition_elapsed = 0.0
                if was_cloaked:
                    self._fire("ET_DECLOAK_COMPLETED")
            return

        if self._cloak_state not in (self.CLOAK_CLOAKING, self.CLOAK_DECLOAKING):
            return

        self._transition_elapsed += float(dt)
        if self._transition_elapsed < self._transition_duration:
            return

        if self._cloak_state == self.CLOAK_CLOAKING:
            self._cloak_state = self.CLOAK_CLOAKED
            self._transition_elapsed = 0.0
            self._fire("ET_CLOAK_COMPLETED")
        else:  # CLOAK_DECLOAKING
            self._cloak_state = self.CLOAK_DECLOAKED
            self._transition_elapsed = 0.0
            self._fire("ET_DECLOAK_COMPLETED")

    # ── Shield coupling ───────────────────────────────────────────────────────

    def _collapse_shields(self) -> None:
        """Drop the owning ship's shields to zero the instant the cloak engages.

        BC forces shields down on cloak (you cannot cloak with shields up), and
        this fires for every trigger path — player toggle, AI doctrine, or
        mission script — because they all funnel through StartCloaking.  The
        per-tick ShieldSubsystem.Update cloak gate then keeps them collapsed
        until decloak.  Raise-safe: a bare cloak with no parent ship (or a ship
        with no shields) simply does nothing."""
        try:
            ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
            if ship is None:
                return
            shields = (ship.GetShieldSubsystem()
                       if hasattr(ship, "GetShieldSubsystem") else None)
            if shields is None:
                return
            for face in range(shields.NUM_SHIELDS):
                shields.SetCurrentShields(face, 0.0)
        except Exception as _e:
            dev_mode.log_swallowed("cloak shield collapse", _e)

    def _stop_weapons(self) -> None:
        """Force the owning ship's weapons offline the instant the cloak engages.

        ``_cloak_blocks_fire`` (weapon_subsystems) already blocks *new* fire
        while IsTryingToCloak, but an already-firing beam keeps going until
        something calls StopFiring — so a ship that cloaks mid-volley would keep
        shooting.  BC drops weapons offline on cloak, so actively stop every
        weapon system here (same trigger path as the shield collapse — player
        toggle, AI doctrine, and mission scripts all funnel through
        StartCloaking).  Raise-safe: a bare cloak with no parent ship simply
        does nothing."""
        try:
            ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
            if ship is None:
                return
            for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                           "GetTorpedoSystem"):
                fn = getattr(ship, getter, None)
                system = fn() if callable(fn) else None
                if system is not None and hasattr(system, "StopFiring"):
                    system.StopFiring()
        except Exception as _e:
            dev_mode.log_swallowed("cloak weapons stop", _e)

    # ── Cloak transition SFX ─────────────────────────────────────────────────

    def _play_cloak_sfx(self, name: str) -> None:
        """Play the cloak/decloak transition sound as a 3D one-shot at the owning
        ship.  ``name`` is the sound-manager key — "Cloak" (sfx/cloak on.wav) or
        "Uncloak" (sfx/cloak off.wav), both loaded by LoadTacticalSounds.  Fires
        for every transition path (player toggle, AI doctrine, mission script)
        because they all funnel through StartCloaking / StopCloaking; the
        no-transition InstantCloak / InstantDecloak jumps stay silent (BC plays
        the sweep only on an actual transition).  Raise-safe: no sound manager
        (headless / tests) or a parentless cloak simply does nothing."""
        try:
            import App
            mgr = getattr(App, "g_kSoundManager", None)
            if mgr is None:
                return
            snd = mgr.GetSound(name)
            if snd is None:
                return
            ship = self._climb_to_ship() if hasattr(self, "_climb_to_ship") else None
            if ship is not None and hasattr(ship, "GetWorldLocation"):
                loc = ship.GetWorldLocation()
                snd.Play(position=(loc.x, loc.y, loc.z))
            else:
                snd.Play()
        except Exception as _e:
            dev_mode.log_swallowed("cloak sfx", _e)

    # _fire is inherited from PoweredSubsystem — cloak events use the same
    # ship-as-destination broadcast seam as ET_SUBSYSTEM_POWER_CHANGED.


# ── Module-level WarpEngineSubsystem helpers ─────────────────────────────────
# SDK callers (WarpSequence.py:95-282) reach for a class-level / engine-default
# warp effect time when sequencing the warp begin / end / flash actions:
#
#     pWS.AddAction(pWarpEndAction, pWarpBeginAction,
#                   App.WarpEngineSubsystem_GetWarpEffectTime() / 2.0)
#
# This is the default warp-transition duration in seconds, independent of any
# specific ship's warp engine.  Default 3.0s matches BC's warp animation length.

_warp_effect_time_default: float = 3.0


def WarpEngineSubsystem_GetWarpEffectTime() -> float:
    return _warp_effect_time_default


def WarpEngineSubsystem_SetWarpEffectTime(seconds: float) -> None:
    """Override the engine-default warp effect time (used by tests)."""
    global _warp_effect_time_default
    _warp_effect_time_default = float(seconds)


def _get_xyz(ship) -> tuple:
    """Read a ship's world-space position as a tuple of floats. Adapts
    to whichever accessor the shim exposes. Falls back to (0, 0, 0) so
    the helper is safe to call against a ship that hasn't been
    positioned yet (e.g. just spawned)."""
    # GetTranslate() returns a TGPoint3 with .x, .y, .z attributes.
    for name in ("GetTranslate", "GetWorldLocation", "GetTranslation", "GetPosition",
                 "GetTranslateXYZ"):
        if hasattr(ship, name):
            try:
                t = getattr(ship, name)()
                # TGPoint3 / any object with .x .y .z
                if hasattr(t, "x") and hasattr(t, "y") and hasattr(t, "z"):
                    return (float(t.x), float(t.y), float(t.z))
                # plain tuple or list
                if isinstance(t, (tuple, list)) and len(t) == 3:
                    return (float(t[0]), float(t[1]), float(t[2]))
            except Exception as _e:
                dev_mode.log_swallowed(f"ship position via {name}", _e)
    # Last resort — direct attribute access for the simplest possible shim.
    if hasattr(ship, "_position"):
        try:
            p = ship._position
            if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                return (float(p.x), float(p.y), float(p.z))
            if isinstance(p, (tuple, list)) and len(p) == 3:
                return (float(p[0]), float(p[1]), float(p[2]))
        except Exception as _e:
            dev_mode.log_swallowed("ship position via _position attr", _e)
    return (0.0, 0.0, 0.0)


# ── Weapon subsystem hierarchy (split out into engine.appc.weapon_subsystems) ──
# The weapon classes are part of this module's public surface; they were moved to
# engine.appc.weapon_subsystems purely to shrink this file. ~30 call sites do
# ``from engine.appc.subsystems import PhaserSystem`` (etc.), so we re-export the
# weapon names here. weapon_subsystems imports the base classes
# (ShipSubsystem / PoweredSubsystem) and shared predicates UP from this module;
# resolving the weapon names lazily via module __getattr__ (PEP 562) keeps that a
# one-way dependency with NO import cycle, regardless of which module is imported
# first. The first access to any weapon name triggers the import, by which point
# both modules are fully loaded.
_WEAPON_EXPORTS = frozenset({
    "WeaponSystem",
    "TorpedoAmmoType",
    "TorpedoSystem",
    "PHASER_MAX_RANGE_GU",
    "PhaserSystem",
    "PulseWeaponSystem",
    "TractorBeamSystem",
    "PhaserBank",
    "PulseWeapon",
    "TractorBeam",
    "TorpedoTube",
    "_EnergyWeaponFireMixin",
    "_resolve_aim_world",
    "_resolve_bank_aim_world",
    "_emitter_in_arc",
    "_init_energy_weapon_state",
    "_resolve_fire_sound",
})


def __getattr__(name):
    """Lazily forward the weapon-subsystem names to engine.appc.weapon_subsystems
    (PEP 562). Keeps the weapon classes importable as ``engine.appc.subsystems.X``
    without an eager import that would create a cycle."""
    if name in _WEAPON_EXPORTS:
        from engine.appc import weapon_subsystems
        return getattr(weapon_subsystems, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(list(globals().keys()) + list(_WEAPON_EXPORTS))
