"""Interim fix: cloak-capable AI ships fall back to the working non-cloak
attack doctrine so they actually fight (instead of parking in the unsupported
CloakAttack tree). See engine/appc/cloak_ai_fallback.py.
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.properties import CloakingSubsystemProperty
from engine.appc.subsystems import (
    SensorSubsystem, PhaserSystem, PhaserBank, ImpulseEngineSubsystem,
)
from engine.appc.ai import PriorityListAI, BuilderAI
import engine.appc.ai_driver as drv
from engine.core.loop import TICK_DELTA
from engine.appc.cloak_ai_fallback import install_cloak_attack_fallback


def _bank(name):
    b = PhaserBank(name)
    b._max_charge = 5.0; b._charge_level = 5.0; b._min_firing_charge = 3.0
    b._max_damage = 1.0; b._max_damage_distance = 5000.0
    b._max_condition = 100.0; b._condition = 100.0; b._disabled_percentage = 0.25
    return b


def _equip(s):
    sen = SensorSubsystem("Sensors")
    sen._max_condition = 100.0; sen._condition = 100.0
    sen._disabled_percentage = 0.5; sen.SetBaseSensorRange(5000.0)
    s.SetSensorSubsystem(sen)
    imp = ImpulseEngineSubsystem("Impulse")
    imp._max_condition = 100.0; imp._condition = 100.0
    imp.SetMaxSpeed(6.0)
    s.SetImpulseEngineSubsystem(imp)
    ph = PhaserSystem("Phasers")
    ph._max_condition = 100.0; ph._condition = 100.0; ph._disabled_percentage = 0.75
    ph.TurnOn()
    for i in range(4):
        ph.AddChildSubsystem(_bank(f"B{i}"))
    s.SetPhaserSystem(ph)


def _cloak_ship(name, x, y):
    s = ShipClass_Create("Warbird")
    s.SetName(name); s.SetTranslateXYZ(x, y, 0.0)
    cp = CloakingSubsystemProperty("Cloaking Device"); cp.SetCloakStrength(100.0)
    s.GetPropertySet().AddToSet("Scene Root", cp); s.SetupProperties()
    _equip(s)
    return s


def _scene():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    atk = _cloak_ship("Atk", 0, 0); pSet.AddObjectToSet(atk, "Atk")
    tgt = ShipClass_Create("Galaxy"); tgt.SetName("Tgt"); tgt.SetTranslateXYZ(0, 300, 0)
    _equip(tgt); pSet.AddObjectToSet(tgt, "Tgt")
    return atk


def test_fallback_routes_cloak_ship_to_non_cloak_doctrine():
    """With the fallback installed, a cloak-capable ship + UseCloaking=1 builds
    the non-cloak BasicAttack doctrine (a BuilderAI) rather than the
    CloakAttackWrapper PriorityListAI that doesn't drive combat."""
    import AI.Compound.CloakAttackWrapper as _caw
    saved = _caw.CreateAI
    try:
        install_cloak_attack_fallback()
        import AI.Compound.BasicAttack as BA
        atk = _scene()
        assert atk.GetCloakingSubsystem() is not None
        ai = BA.CreateAI(atk, ["Tgt"], UseCloaking=1)
        # Non-cloak doctrine is a BuilderAI; the broken cloak path is a
        # PriorityListAI.
        assert isinstance(ai, BuilderAI)
        assert not isinstance(ai, PriorityListAI)
    finally:
        _caw.CreateAI = saved


def test_fallback_cloak_ship_acquires_target_and_fights():
    """End-to-end: with the fallback, a cloak ship actually acquires a target
    (the regression was that it never did)."""
    import AI.Compound.CloakAttackWrapper as _caw
    saved = _caw.CreateAI
    try:
        install_cloak_attack_fallback()
        import AI.Compound.BasicAttack as BA
        atk = _scene()
        ai = BA.CreateAI(atk, ["Tgt"], UseCloaking=1)
        clk = atk.GetCloakingSubsystem()
        gt = 0.0
        ever_target = False
        for _ in range(40):
            drv.tick_ai(ai, game_time=gt)
            clk.Update(TICK_DELTA)
            gt += TICK_DELTA
            if atk.GetTarget() is not None:
                ever_target = True
                break
        assert ever_target, "cloak ship still never acquired a target"
    finally:
        _caw.CreateAI = saved
