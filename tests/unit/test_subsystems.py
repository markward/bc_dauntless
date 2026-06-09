import App
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, WeaponSystem,
    TorpedoSystem, PhaserSystem, PulseWeaponSystem, TractorBeamSystem,
    SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
)
from engine.appc.ships import ShipClass


def test_subsystem_world_location_rotates_offset():
    """GetWorldLocation must rotate the local mount through the ship's
    world rotation (R · local), not add the raw body-frame offset."""
    import math
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.appc.subsystems import ShipSubsystem, subsystem_world_position

    class _FakeShip:
        def __init__(self, loc, rot):
            self._loc, self._rot = loc, rot
        def GetWorldLocation(self):  return self._loc
        def GetWorldRotation(self):  return self._rot

    # 90° yaw about Z: ship-+X local maps to world +Y (column-vector R).
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)
    ship = _FakeShip(TGPoint3(100.0, 0.0, 0.0), R)

    sub = ShipSubsystem("Port Nacelle")
    sub._position = TGPoint3(10.0, 0.0, 0.0)    # +10 along ship local X
    sub.SetParentShip(ship)

    w = sub.GetWorldLocation()
    # R·(10,0,0) for a +90° Z rotation = (0, 10, 0); plus ship loc (100,0,0).
    assert abs(w.x - 100.0) < 1e-5
    assert abs(w.y -  10.0) < 1e-5
    assert abs(w.z -   0.0) < 1e-5
    # The free function must agree with the method.
    w2 = subsystem_world_position(sub, ship)
    assert abs(w.x - w2.x) < 1e-9 and abs(w.y - w2.y) < 1e-9 and abs(w.z - w2.z) < 1e-9


def test_subsystem_class_hierarchy():
    assert issubclass(TorpedoSystem, WeaponSystem)
    assert issubclass(PhaserSystem, WeaponSystem)
    assert issubclass(PulseWeaponSystem, WeaponSystem)
    assert issubclass(TractorBeamSystem, WeaponSystem)
    assert issubclass(WeaponSystem, ShipSubsystem)
    assert issubclass(SensorSubsystem, PoweredSubsystem)
    assert issubclass(ImpulseEngineSubsystem, PoweredSubsystem)
    assert issubclass(WarpEngineSubsystem, PoweredSubsystem)
    assert issubclass(PoweredSubsystem, ShipSubsystem)


def test_subsystem_name_round_trip():
    s = ShipSubsystem("Hull")
    assert s.GetName() == "Hull"
    s.SetName("New Hull")
    assert s.GetName() == "New Hull"


def test_subsystem_condition_defaults():
    s = ShipSubsystem("Hull")
    assert s.GetCondition() == 1.0
    assert s.GetMaxCondition() == 1.0
    assert s.GetConditionPercentage() == 1.0
    assert s.GetCombinedConditionPercentage() == 1.0
    assert s.GetDamage() == 0.0


def test_weapon_system_target_round_trip():
    w = PhaserSystem("Forward Phasers")
    target = ShipClass()
    w.SetTarget(target)
    assert w.GetTarget() is target


def test_torpedo_system_ammo_types():
    t = TorpedoSystem("Torpedo Bay")
    assert t.GetNumAmmoTypes() == 0
    t.AddAmmoType("Photon")
    t.AddAmmoType("Quantum")
    assert t.GetNumAmmoTypes() == 2


def test_warp_engine_warp_state_round_trip():
    w = WarpEngineSubsystem("Warp Drive")
    assert w.GetWarpState() == WarpEngineSubsystem.WES_NOT_WARPING
    w.SetWarpState(WarpEngineSubsystem.WES_WARPING)
    assert w.GetWarpState() == WarpEngineSubsystem.WES_WARPING


def test_warp_engine_constants_distinct():
    states = {
        WarpEngineSubsystem.WES_NOT_WARPING,
        WarpEngineSubsystem.WES_WARP_INITIATED,
        WarpEngineSubsystem.WES_WARP_BEGINNING,
        WarpEngineSubsystem.WES_WARP_ENDING,
        WarpEngineSubsystem.WES_WARPING,
        WarpEngineSubsystem.WES_DEWARP_INITIATED,
        WarpEngineSubsystem.WES_DEWARP_BEGINNING,
        WarpEngineSubsystem.WES_DEWARP_ENDING,
    }
    assert len(states) == 8


def test_tractor_beam_mode_constants_distinct():
    modes = {
        TractorBeamSystem.TBS_HOLD,
        TractorBeamSystem.TBS_TOW,
        TractorBeamSystem.TBS_PULL,
        TractorBeamSystem.TBS_PUSH,
        TractorBeamSystem.TBS_DOCK_STAGE_1,
        TractorBeamSystem.TBS_DOCK_STAGE_2,
    }
    assert len(modes) == 6


def test_phaser_power_level_constants():
    assert PhaserSystem.PP_LOW != PhaserSystem.PP_HIGH


def test_phaser_power_level_round_trip():
    p = PhaserSystem("Forward Phasers")
    p.SetPowerLevel(PhaserSystem.PP_LOW)
    assert p.GetPowerLevel() == PhaserSystem.PP_LOW


def test_powered_subsystem_power_round_trip():
    s = SensorSubsystem("Sensors")
    s.SetNormalPowerPerSecond(15.5)
    assert s.GetNormalPowerPerSecond() == 15.5


def test_subsystem_world_location_falls_back_to_local_when_no_parent():
    from engine.appc.math import TGPoint3
    s = ShipSubsystem("Hull")
    s._position = TGPoint3(1.0, 2.0, 3.0)
    loc = s.GetWorldLocation()
    assert (loc.x, loc.y, loc.z) == (1.0, 2.0, 3.0)


def test_app_module_exposes_subsystem_classes_and_constants():
    """SDK callers do `App.WarpEngineSubsystem.WES_NOT_WARPING`
    and `App.TractorBeamSystem.TBS_TOW` etc."""
    assert App.WarpEngineSubsystem.WES_NOT_WARPING == 0
    assert App.TractorBeamSystem.TBS_TOW == 1
    assert App.PhaserSystem.PP_LOW == 0
    assert App.PhaserSystem.PP_HIGH == 1


# ── WarpEngineSubsystem_GetWarpEffectTime module-level wrapper ───────────────

def test_module_level_warp_effect_time_default():
    """SDK pattern: pSeq.AddAction(a, b, App.WarpEngineSubsystem_GetWarpEffectTime() / 2.0)."""
    t = App.WarpEngineSubsystem_GetWarpEffectTime()
    assert isinstance(t, float)
    assert t > 0.0   # must be positive so the / 2.0 division gives a real delay


def test_module_level_warp_effect_time_set_round_trip():
    original = App.WarpEngineSubsystem_GetWarpEffectTime()
    App.WarpEngineSubsystem_SetWarpEffectTime(5.0)
    assert App.WarpEngineSubsystem_GetWarpEffectTime() == 5.0
    # Restore for other tests.
    App.WarpEngineSubsystem_SetWarpEffectTime(original)


def test_module_level_warp_effect_time_independent_from_instance():
    """Each WarpEngineSubsystem instance has its own GetWarpEffectTime;
    the module-level default is engine-wide and not tied to any one ship."""
    inst = WarpEngineSubsystem()
    inst.SetWarpEffectTime(99.0)
    # Module-level value is unchanged.
    assert App.WarpEngineSubsystem_GetWarpEffectTime() != 99.0
    assert inst.GetWarpEffectTime() == 99.0
