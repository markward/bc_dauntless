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
                data[(field, _hashable_key(args[:-1]))] = args[-1]
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            data = self._data
            def getter(*args):
                return data.get((field, _hashable_key(args)), None)
            return getter
        raise AttributeError(attr)


def _hashable_key(args: tuple) -> tuple:
    """Convert a tuple of args into a hashable key.

    Falls back to repr() for any element that isn't hashable (e.g.
    TGPoint3, which defines __eq__ but not __hash__). This keeps the
    data-bag tolerant of SDK setters that pass unhashable arguments
    such as SetOrientation(forward_vec, up_vec).
    """
    try:
        hash(args)
        return args
    except TypeError:
        return tuple(
            a if _is_hashable(a) else repr(a)
            for a in args
        )


def _is_hashable(value) -> bool:
    try:
        hash(value)
        return True
    except TypeError:
        return False


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


# ── TGModelPropertyManager ────────────────────────────────────────────────────
# loadspacehelper.py:90 calls ClearLocalTemplates() between ship loads, so the
# manager is genuinely stateful across hardpoint imports. App.py's singleton
# lives for the whole session.
#
# Renderer-only methods (RegisterFilter, AddFilter, ApplyFilters, etc.) are
# Phase 2 concerns; they fall through to App.py's _NamedStub via __getattr__.

class TGModelPropertyManager:
    LOCAL_TEMPLATES  = 0
    GLOBAL_TEMPLATES = 1

    def __init__(self):
        self._local: dict = {}
        self._global: dict = {}

    def _store(self, scope):
        return self._local if scope == self.LOCAL_TEMPLATES else self._global

    def RegisterLocalTemplate(self, prop):
        self._local[prop.GetName()] = prop

    def RegisterGlobalTemplate(self, prop):
        self._global[prop.GetName()] = prop

    def ClearLocalTemplates(self):
        self._local.clear()

    def ClearGlobalTemplates(self):
        self._global.clear()

    def FindByName(self, name, scope):
        return self._store(scope).get(name)

    def FindByNameAndType(self, name, type_cls, scope):
        prop = self._store(scope).get(name)
        return prop if isinstance(prop, type_cls) else None

    def IsLocalTemplate(self, prop):
        return prop in self._local.values()

    def IsGlobalTemplate(self, prop):
        return prop in self._global.values()

    def RemoveTemplate(self, prop):
        self._local  = {k: v for k, v in self._local.items()  if v is not prop}
        self._global = {k: v for k, v in self._global.items() if v is not prop}


# ── TGModelPropertySet ────────────────────────────────────────────────────────
# Holds (node_name, prop) pairs. node_name (e.g. "Scene Root") is a renderer
# concept stored but unused in Phase 1.

class TGModelPropertySet:
    def __init__(self):
        self._entries: list = []

    def AddToSet(self, node_name, prop):
        self._entries.append((node_name, prop))

    def GetPropertyList(self):
        return iter([prop for _node, prop in self._entries])

    def GetPropertiesByType(self, type_cls):
        return iter([prop for _node, prop in self._entries if isinstance(prop, type_cls)])
