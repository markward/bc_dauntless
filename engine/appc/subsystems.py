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

    def GetDisabledPercentage(self) -> float:
        # SDK SubsystemProperty.GetDisabledPercentage: fraction of max condition
        # below which the subsystem is "disabled".  Default 0.25 matches the
        # Appc default for systems where the property hasn't overridden it.
        return 0.25


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


class WeaponSystem(ShipSubsystem):
    """Weapon system — has firing state and an optional target."""
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._firing = False
        self._target = None

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

    def SetPowerLevel(self, level) -> None:
        self._power_level = int(level)

    def GetPowerLevel(self) -> int:
        return self._power_level


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


class SensorSubsystem(PoweredSubsystem):
    pass


class ImpulseEngineSubsystem(PoweredSubsystem):
    pass


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
