"""TGModelProperty hierarchy + manager.

See docs/project/superpowers/specs/2026-05-08-model-property-manager-design.md.
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
            cls_name = type(self).__name__
            def setter(*args):
                data[(field, _hashable_key(args[:-1]))] = args[-1]
                # Empirical consumer tracking: if any arg is a TGColorA, log
                # which shim setter received it (off unless harness enables).
                import App as _App
                if _App._color_consumer_tracker.is_enabled():
                    for a in args:
                        if isinstance(a, _App.TGColorA):
                            import sys as _sys
                            frame = _sys._getframe(1)
                            _App._color_consumer_tracker.record(
                                f"{cls_name}.{attr}", a,
                                frame.f_code.co_filename, frame.f_lineno,
                            )
                            break
            return setter
        if attr.startswith("Get"):
            field = attr[3:]
            data = self._data
            def getter(*args):
                return data.get((field, _hashable_key(args)), None)
            return getter
        raise AttributeError(attr)


def _copy_point(p):
    """Fresh TGPoint3 copy, or None if the source is None.

    Matches SDK semantics where Get*() returns a copy callers can mutate
    (e.g. via MultMatrixLeft) without affecting the template.
    """
    if p is None:
        return None
    from engine.appc.math import TGPoint3
    return TGPoint3(p.x, p.y, p.z)


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


class ObjectEmitterProperty(PositionOrientationProperty):
    """Emitter point on a hull (shuttle / probe / decoy launch position).

    SDK hierarchy: ObjectEmitterProperty extends PositionOrientationProperty.
    Hardpoint scripts populate position, orientation, and emitted object type
    via SetPosition / SetOrientation / SetEmittedObjectType; the LaunchObject
    action reads them back to compute world-frame launch transforms.
    """

    OEP_UNKNOWN = 0
    OEP_SHUTTLE = 1
    OEP_PROBE   = 2
    OEP_DECOY   = 3

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._forward = None
        self._up = None
        self._right = None
        self._position = None
        self._emitted_type = self.OEP_UNKNOWN

    def SetOrientation(self, fwd, up, right):
        self._forward = _copy_point(fwd)
        self._up = _copy_point(up)
        self._right = _copy_point(right)

    def GetForward(self):
        return _copy_point(self._forward)

    def GetUp(self):
        return _copy_point(self._up)

    def GetRight(self):
        return _copy_point(self._right)

    def SetPosition(self, p):
        self._position = _copy_point(p)

    def GetPosition(self):
        return _copy_point(self._position)

    def SetEmittedObjectType(self, t):
        self._emitted_type = int(t)

    def GetEmittedObjectType(self):
        return self._emitted_type


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

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._max_shields = [0.0] * self.NUM_SHIELDS
        self._charge_per_second = [0.0] * self.NUM_SHIELDS
        self._skin_shielding: int = 0
        self._shield_glow_decay: float = 1.0
        self._shield_glow_color = None

    def GetMaxShields(self, face):
        return self._max_shields[int(face)]

    def SetMaxShields(self, face, value):
        f = int(face)
        v = float(value)
        self._max_shields[f] = v

    def GetShieldChargePerSecond(self, face):
        return self._charge_per_second[int(face)]

    def SetShieldChargePerSecond(self, face, value):
        f = int(face)
        v = float(value)
        self._charge_per_second[f] = v

    def GetSkinShielding(self):
        return self._skin_shielding

    def SetSkinShielding(self, value):
        self._skin_shielding = int(value)

    def GetShieldGlowDecay(self):
        return self._shield_glow_decay

    def SetShieldGlowDecay(self, value):
        self._shield_glow_decay = float(value)

    def GetShieldGlowColor(self):
        return self._shield_glow_color

    def SetShieldGlowColor(self, color):
        self._shield_glow_color = color
        # Preserve the color-consumer tracker hook that TGModelProperty's
        # auto-synthesized setter used to provide.  Matches the shim's
        # _getframe(1) caller-attribution behavior in properties.py:32-43.
        import App as _App
        if _App._color_consumer_tracker.is_enabled():
            import sys as _sys
            frame = _sys._getframe(1)
            _App._color_consumer_tracker.record(
                "ShieldProperty.SetShieldGlowColor", color,
                frame.f_code.co_filename, frame.f_lineno,
            )


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


# Ship template — top-level data container for ship-class definitions
# (mass, model, affiliation, AI string, etc).  See sdk/.../GlobalPropertyTemplates.py
# and ships/Hardpoints/*.py for setter call sites.
class ShipProperty(TGModelProperty):
    pass


# Engine subsystems.  EngineProperty is the lightweight type-tagged form used
# by hardpoint scripts that need named per-engine entries (Port Warp, Star Warp).
# Impulse/WarpEngineProperty are powered-subsystem forms with speed/accel data.
class EngineProperty(SubsystemProperty):
    EP_IMPULSE = 0
    EP_WARP    = 1


class ImpulseEngineProperty(PoweredSubsystemProperty):
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._engine_sound_name: str = ""

    def SetEngineSound(self, name: str) -> None:
        self._engine_sound_name = name or ""

    def GetEngineSound(self) -> str:
        return self._engine_sound_name


class WarpEngineProperty(PoweredSubsystemProperty):
    pass


# Cloaking system — used by birdofprey, warbird, vorcha, sunbuster, kessok*
# (sdk/.../ships/Hardpoints/*).  Powered subsystem with a single domain-specific
# attribute (CloakStrength) plus the inherited subsystem fields.
class CloakingSubsystemProperty(PoweredSubsystemProperty):
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
def ShipProperty_Create(name):                return ShipProperty(name)
def EngineProperty_Create(name):              return EngineProperty(name)
def ImpulseEngineProperty_Create(name):       return ImpulseEngineProperty(name)
def WarpEngineProperty_Create(name):          return WarpEngineProperty(name)
def WeaponSystemProperty_Create(name):        return WeaponSystemProperty(name)
def CloakingSubsystemProperty_Create(name):   return CloakingSubsystemProperty(name)
def ObjectEmitterProperty_Create(name):       return ObjectEmitterProperty(name)


def ObjectEmitterProperty_Cast(obj):
    """Lenient pass-through: returns obj if it's an ObjectEmitterProperty, else None.

    Rejects _NamedStub explicitly so undefined-attribute chains don't slip
    through and keep producing stub-tracker hits.
    """
    if obj is None:
        return None
    import App
    if isinstance(obj, App._NamedStub):
        return None
    if isinstance(obj, ObjectEmitterProperty):
        return obj
    return None


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


# ── TGModelPropertyInstance / TGModelPropertyList ─────────────────────────────
# SDK call sites (loadspacehelper.py:171-189) iterate the result of
# GetPropertyList()/GetPropertiesByType() via TGBeginIteration / TGGetNumItems
# / TGGetNext / TGDoneIterating / TGDestroy. TGGetNext returns an "instance"
# wrapper exposing GetProperty() to extract the underlying TGModelProperty —
# see SDK App.py:2316-2342 for reference.

class _TGModelPropertyInstance:
    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self):
        return self._prop


class _TGModelPropertyList:
    def __init__(self, props):
        self._props = list(props)
        self._index = 0

    def __iter__(self):
        # Preserve Python list() compatibility for tests/non-SDK callers.
        return iter(self._props)

    def TGBeginIteration(self):
        self._index = 0

    def TGGetNumItems(self):
        return len(self._props)

    def TGGetNext(self):
        prop = self._props[self._index]
        self._index += 1
        return _TGModelPropertyInstance(prop)

    def TGDoneIterating(self):
        self._index = 0

    def TGDestroy(self):
        pass


# ── TGModelPropertySet ────────────────────────────────────────────────────────
# Holds (node_name, prop) pairs. node_name (e.g. "Scene Root") is a renderer
# concept stored but unused in Phase 1.

class TGModelPropertySet:
    def __init__(self):
        self._entries: list = []

    def AddToSet(self, node_name, prop):
        self._entries.append((node_name, prop))

    def GetPropertyList(self):
        return _TGModelPropertyList([prop for _node, prop in self._entries])

    def GetPropertiesByType(self, type_cls):
        return _TGModelPropertyList(
            [prop for _node, prop in self._entries if isinstance(prop, type_cls)]
        )
