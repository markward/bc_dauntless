"""TGModelProperty hierarchy + manager.

See docs/superpowers/specs/2026-05-08-model-property-manager-design.md.
"""


class TGModelProperty:
    def __init__(self, name: str):
        self._name = name
        self._data: dict = {}

    def GetName(self) -> str:
        return self._name

    def SetName(self, value: str) -> None:
        self._name = value

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self._name!r}>"

    def __getattr__(self, attr: str):
        if attr.startswith("Set"):
            field = attr[3:]
            data = self._data
            def setter(*args):
                data[(field, args[:-1])] = args[-1]
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            data = self._data
            def getter(*args):
                return data.get((field, args), None)
            return getter
        raise AttributeError(attr)


# ── Subclass hierarchy ────────────────────────────────────────────────────────
# Subclasses are thin: only class-level constants. All Set*/Get* behaviour is
# inherited from the data-bag base.

class PositionOrientationProperty(TGModelProperty):
    pass


class EngineGlowProperty(TGModelProperty):
    pass


class SubsystemProperty(TGModelProperty):
    pass


class HullProperty(SubsystemProperty):
    pass


class PowerProperty(SubsystemProperty):
    pass


class WeaponProperty(SubsystemProperty):
    pass


class EnergyWeaponProperty(WeaponProperty):
    pass


class PhaserProperty(EnergyWeaponProperty):
    pass


class PulseWeaponProperty(EnergyWeaponProperty):
    pass


class TractorBeamProperty(EnergyWeaponProperty):
    pass


class TorpedoTubeProperty(WeaponProperty):
    pass


class PoweredSubsystemProperty(SubsystemProperty):
    pass


class ShieldProperty(PoweredSubsystemProperty):
    FRONT_SHIELDS  = 0
    REAR_SHIELDS   = 1
    TOP_SHIELDS    = 2
    BOTTOM_SHIELDS = 3
    LEFT_SHIELDS   = 4
    RIGHT_SHIELDS  = 5
    NUM_SHIELDS    = 6


class SensorProperty(PoweredSubsystemProperty):
    pass


class RepairSubsystemProperty(PoweredSubsystemProperty):
    pass


class WeaponSystemProperty(PoweredSubsystemProperty):
    WST_UNKNOWN = 0
    WST_PHASER  = 1
    WST_TORPEDO = 2
    WST_PULSE   = 3
    WST_TRACTOR = 4


class TorpedoSystemProperty(WeaponSystemProperty):
    pass


# ── Factory functions ─────────────────────────────────────────────────────────
# SDK call sites use App.XxxProperty_Create("Name") rather than the
# constructor directly. These mirror the SDK's Appc.new_XxxProperty pattern.

def PositionOrientationProperty_Create(name): return PositionOrientationProperty(name)
def HullProperty_Create(name):                return HullProperty(name)
def PowerProperty_Create(name):               return PowerProperty(name)
def PhaserProperty_Create(name):              return PhaserProperty(name)
def PulseWeaponProperty_Create(name):         return PulseWeaponProperty(name)
def TractorBeamProperty_Create(name):         return TractorBeamProperty(name)
def TorpedoTubeProperty_Create(name):         return TorpedoTubeProperty(name)
def ShieldProperty_Create(name):              return ShieldProperty(name)
def SensorProperty_Create(name):              return SensorProperty(name)
def RepairSubsystemProperty_Create(name):     return RepairSubsystemProperty(name)
def TorpedoSystemProperty_Create(name):       return TorpedoSystemProperty(name)
