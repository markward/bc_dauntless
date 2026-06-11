# tests/unit/test_subsystem_emitters_registry.py
"""Registry + descriptor + kind-derivation tests for the plume state machine."""
from engine.appc import subsystem_emitters as se
from engine.appc.math import TGPoint3


# ---- shared fakes (imported by later test modules) -------------------------

class FakeSub:
    """A minimal subsystem: settable damage state + class-name kind + anchor."""
    def __init__(self, kind_class_name="WarpEngineSubsystem", name="nacelle",
                 pos=(1.0, -2.0, 0.5), state="ok"):
        # Per-instance subclass so type(sub).__name__ is unique per instance
        # (mutating FakeSub.__name__ directly would be shared across all instances).
        self.__class__ = type(kind_class_name, (FakeSub,), {})
        self._name = name
        self._pos = TGPoint3(*pos)
        self._state = state  # "ok" | "damaged" | "disabled" | "destroyed"

    def GetName(self):       return self._name
    def GetPosition(self):   return TGPoint3(self._pos.x, self._pos.y, self._pos.z)
    def IsDamaged(self):     return 1 if self._state in ("damaged",) else 0
    def IsDisabled(self):    return 1 if self._state in ("disabled",) else 0
    def IsDestroyed(self):   return 1 if self._state == "destroyed" else 0


class _Mat3Identity:
    def GetCol(self, i):
        return [TGPoint3(1, 0, 0), TGPoint3(0, 1, 0), TGPoint3(0, 0, 1)][i]


class FakeShip:
    def __init__(self, obj_id=1, subs=None, loc=(0.0, 0.0, 0.0)):
        self._id = obj_id
        self._subs = subs or []
        self._loc = TGPoint3(*loc)

    def GetObjID(self):        return self._id
    def GetSubsystems(self):   return list(self._subs)
    def GetWorldLocation(self):return TGPoint3(self._loc.x, self._loc.y, self._loc.z)
    def GetWorldRotation(self):return _Mat3Identity()


# ---- registry tests --------------------------------------------------------

def _fresh():
    se.reset_registry()  # restores built-in defaults, clears mod additions


def test_builtin_table_resolves_warp_engine_tiers():
    _fresh()
    d_dmg = se.resolve("warp_engine", se.TIER_DAMAGED)
    d_dis = se.resolve("warp_engine", se.TIER_DISABLED)
    assert d_dmg is not None and d_dis is not None
    assert d_dmg.factory == "CreateSmokeHigh"
    assert d_dmg.direction_mode == se.DirectionMode.FIXED_BODY_VECTOR
    assert d_dmg.direction_vec == (0.0, -1.0, 0.0)  # aft


def test_warp_core_defaults_spherical():
    _fresh()
    d = se.resolve("warp_core", se.TIER_DAMAGED)
    assert d.direction_mode == se.DirectionMode.SPHERICAL


def test_shield_generator_has_no_sustained_entry():
    _fresh()
    assert se.resolve("shield_generator", se.TIER_DAMAGED) is None
    assert se.resolve("shield_generator", se.TIER_DISABLED) is None


def test_register_overrides_a_cell():
    _fresh()
    custom = se.PlumeDescriptor(factory="CreateDebrisSmoke", params={"fSize": 9.0},
                                direction_mode=se.DirectionMode.SPHERICAL)
    se.register("warp_engine", se.TIER_DAMAGED, custom)
    assert se.resolve("warp_engine", se.TIER_DAMAGED) is custom


def test_register_new_kind_lights_up():
    _fresh()
    d = se.PlumeDescriptor(factory="CreateSmokeHigh", params={},
                           direction_mode=se.DirectionMode.SPHERICAL)
    se.register("antimatter_pod", se.TIER_DISABLED, d)
    assert se.resolve("antimatter_pod", se.TIER_DISABLED) is d


def test_unregister_removes_cell():
    _fresh()
    se.unregister("warp_engine", se.TIER_DAMAGED)
    assert se.resolve("warp_engine", se.TIER_DAMAGED) is None


def test_subsystem_kind_from_class_name():
    _fresh()
    assert se.subsystem_kind(FakeSub("WarpEngineSubsystem")) == "warp_engine"
    assert se.subsystem_kind(FakeSub("ImpulseEngineSubsystem")) == "impulse_engine"
    assert se.subsystem_kind(FakeSub("PowerSubsystem")) == "warp_core"
    assert se.subsystem_kind(FakeSub("ShieldSubsystem")) == "shield_generator"
    assert se.subsystem_kind(FakeSub("SensorSubsystem")) is None  # no plume


def test_kind_alias_routes_modded_class():
    _fresh()
    se.register_kind_alias("ModWarpRing", "warp_engine")
    assert se.subsystem_kind(FakeSub("ModWarpRing")) == "warp_engine"
