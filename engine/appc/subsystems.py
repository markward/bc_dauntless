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

from engine.appc.events import TGEventHandlerObject
from engine.appc.math import TGPoint3


class ShipSubsystem(TGEventHandlerObject):
    def __init__(self, name: str = ""):
        super().__init__()
        self._name = name
        self._property = None
        self._parent_ship = None
        self._parent_subsystem = None
        self._child_subsystem = None
        self._condition = 1.0
        self._max_condition = 1.0
        self._radius = 0.0
        self._position = TGPoint3(0.0, 0.0, 0.0)
        # Shared identity fields populated by SetupProperties.
        self._critical: int = 0
        self._targetable: int = 0
        self._primary: int = 0
        self._disabled_percentage: float = 0.25

    def GetName(self) -> str:
        return self._name

    def SetName(self, name: str) -> None:
        self._name = name

    def GetProperty(self):
        return self._property

    def SetProperty(self, prop) -> None:
        self._property = prop

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

    def GetMaxCondition(self) -> float:
        return self._max_condition

    def SetMaxCondition(self, value: float) -> None:
        # SDK App.py:5601 — also seed current condition when bumping max from
        # the default so freshly-loaded ships start undamaged.
        v = float(value)
        if self._condition == self._max_condition:
            self._condition = v
        self._max_condition = v

    def GetConditionPercentage(self) -> float:
        if self._max_condition <= 0:
            return 0.0
        return self._condition / self._max_condition

    def GetCombinedConditionPercentage(self) -> float:
        # SDK aggregates self + child subsystems; Phase 1 ships have no
        # children so this collapses to the same value.
        return self.GetConditionPercentage()

    def GetDamage(self) -> float:
        return self._max_condition - self._condition

    def GetRepairPointsNeeded(self) -> int:
        return int(self._max_condition - self._condition)

    def GetRadius(self) -> float:
        return self._radius

    def SetRadius(self, value: float) -> None:
        self._radius = float(value)

    def GetPositionTG(self) -> TGPoint3:
        return TGPoint3(self._position.x, self._position.y, self._position.z)

    def GetPosition(self) -> TGPoint3:
        return self.GetPositionTG()

    def GetWorldLocation(self) -> TGPoint3:
        if self._parent_ship is not None:
            base = self._parent_ship.GetWorldLocation()
            return TGPoint3(
                base.x + self._position.x,
                base.y + self._position.y,
                base.z + self._position.z,
            )
        return self.GetPositionTG()

    def GetDamagePoint(self) -> TGPoint3:
        return self.GetPositionTG()

    def GetNextTargetableChildSubsystem(self):
        return None

    def GetConditionWatcher(self):
        return None

    def GetCombinedPercentageWatcher(self):
        return None

    # ── Child-subsystem walking ──────────────────────────────────────────────
    # SDK consumers iterate child subsystems via GetNumChildSubsystems +
    # GetChildSubsystem(i) (e.g. E2M2 PrepMarauder, E5M2 CreateGeronimo).
    # Phase 1 ships have no decomposition, so the iteration empties cleanly.

    def GetNumChildSubsystems(self) -> int:
        return 0

    def GetChildSubsystem(self, index_or_name=None):
        return None

    def GetCritical(self) -> int:                       return self._critical
    def SetCritical(self, v) -> None:                   self._critical = int(v)
    def GetTargetable(self) -> int:                     return self._targetable
    def SetTargetable(self, v) -> None:                 self._targetable = int(v)
    def GetPrimary(self) -> int:                        return self._primary
    def SetPrimary(self, v) -> None:                    self._primary = int(v)
    def GetDisabledPercentage(self) -> float:           return self._disabled_percentage
    def SetDisabledPercentage(self, v) -> None:         self._disabled_percentage = float(v)


class PoweredSubsystem(ShipSubsystem):
    """Powered subsystem — consumes power, has a target power level."""
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._normal_power = 0.0
        self._current_power = 0.0

    def GetNormalPowerPerSecond(self) -> float:
        return self._normal_power

    def SetNormalPowerPerSecond(self, value: float) -> None:
        self._normal_power = float(value)

    def GetPowerPerSecond(self) -> float:
        return self._current_power

    def SetPowerPerSecond(self, value: float) -> None:
        self._current_power = float(value)


class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line.  See sdk/.../App.py:6361 (WeaponSystem inherits
    PoweredSubsystem there).
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._firing = False
        self._target = None
        self._weapon_system_type: int = 0

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def StartFiring(self, *args) -> None:
        self._firing = True

    def StopFiring(self, *args) -> None:
        self._firing = False

    def GetTarget(self):
        return self._target

    def SetTarget(self, target) -> None:
        self._target = target

    def GetWeaponSystemType(self) -> int:           return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:       self._weapon_system_type = int(v)


class TorpedoAmmoType:
    """A loaded torpedo ammo type — exposes the SDK GetAmmoName surface.

    Real BC Appc has a TorpedoAmmoType class with per-instance ammo properties
    (damage, blast radius, etc.); Phase 1 only needs the name for the
    MissionLib.SetTotalTorpsAtStarbase / LoadTorpedoes lookup pattern, which
    compares ``pTorpType.GetAmmoName() == "Photon"``.
    """
    def __init__(self, name: str):
        self._name = name

    def GetAmmoName(self) -> str:
        return self._name

    def __repr__(self) -> str:
        return f"<TorpedoAmmoType {self._name!r}>"


class TorpedoSystem(WeaponSystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        # Keyed slot table — `SetAmmoType(slot, ammo)` is the SDK setter
        # mission scripts use to swap loadouts (E2M0 sets Birds-of-Prey to
        # AT_TWO photon torpedoes).  GetNumAmmoTypes counts populated slots.
        self._ammo_by_slot: dict = {}

    def GetNumAmmoTypes(self) -> int:
        return len(self._ammo_by_slot)

    def AddAmmoType(self, ammo_type) -> None:
        # Append into the next free slot.  Mission code uses either AddAmmoType
        # (during hardpoint setup) or SetAmmoType (during mission to override).
        self._ammo_by_slot[len(self._ammo_by_slot)] = ammo_type

    def SetAmmoType(self, ammo_or_slot, slot_or_ammo=None) -> None:
        # SDK signature: SetAmmoType(ammo_type, slot).  E2M0 calls
        # `pTorps.SetAmmoType(App.AT_TWO, 0)`.  Both args are ints so we
        # don't need to disambiguate by type — first arg = ammo, second = slot.
        if slot_or_ammo is None:
            self._ammo_by_slot[0] = ammo_or_slot
        else:
            self._ammo_by_slot[int(slot_or_ammo)] = ammo_or_slot

    def GetAmmoType(self, slot: int):
        return self._ammo_by_slot.get(int(slot))


class PhaserSystem(WeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446.
    PP_LOW = 0
    PP_HIGH = 1

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._single_fire: int = 0
        self._aimed_weapon: int = 0

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetSingleFire(self) -> int:                 return self._single_fire
    def SetSingleFire(self, v) -> None:             self._single_fire = int(v)
    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)


class PulseWeaponSystem(WeaponSystem):
    pass


class TractorBeamSystem(WeaponSystem):
    # Tractor-beam mode constants from sdk/.../App.py:6774-6779.
    # SDK consumers: Preprocessors.py, AI/PlainAI/Warp.py, TowAway.py, etc.
    TBS_HOLD          = 0
    TBS_TOW           = 1
    TBS_PULL          = 2
    TBS_PUSH          = 3
    TBS_DOCK_STAGE_1  = 4
    TBS_DOCK_STAGE_2  = 5

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._mode = self.TBS_HOLD

    def GetMode(self) -> int:
        return self._mode

    def SetMode(self, mode) -> None:
        self._mode = int(mode)

    def IsTryingToFire(self) -> int:
        return self.IsFiring()


class HullSubsystem(ShipSubsystem):
    """Live hull state.  Hull isn't a powered subsystem — it just tracks
    condition (max + current) so damage logic can read GetMaxCondition()."""
    pass


class SensorSubsystem(PoweredSubsystem):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._base_sensor_range: float = 0.0
        self._max_probes: int = 0

    def GetBaseSensorRange(self) -> float:           return self._base_sensor_range
    def SetBaseSensorRange(self, v) -> None:         self._base_sensor_range = float(v)
    def GetMaxProbes(self) -> int:                   return self._max_probes
    def SetMaxProbes(self, v) -> None:               self._max_probes = int(v)


class ImpulseEngineSubsystem(PoweredSubsystem):
    """Live impulse-engine state.  Speed/accel limits come from the
    matching ImpulseEngineProperty template via ShipClass.SetupProperties()."""

    def __init__(self, name: str = ""):
        super().__init__(name)
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
    NUM_FACES = 6

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields:       list[float] = [0.0] * self.NUM_FACES
        self._current_shields:   list[float] = [0.0] * self.NUM_FACES
        self._charge_per_second: list[float] = [0.0] * self.NUM_FACES

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
        self._current_shields[int(face)] = float(value)

    def GetShieldChargePerSecond(self, face: int) -> float:
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face: int, value: float) -> None:
        self._charge_per_second[int(face)] = float(value)


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
