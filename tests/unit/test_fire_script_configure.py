"""FireScript.ConfigureWeaponSystem per-weapon-type branches.

SDK Preprocessors.py:471-531 — phaser power, torp type selection,
tractor beam mode, default pass-through."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TractorBeamSystem,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_fire_script_with_target():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    from AI.Preprocessors import FireScript
    inst = FireScript("Target")
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp
    return inst, target


def test_configure_phaser_low_power_when_not_high_power():
    inst, target = _build_fire_script_with_target()
    inst.bHighPower = 0
    p = PhaserSystem("P")
    ok = inst.ConfigureWeaponSystem(p, target, None)
    assert ok == 1
    assert p.GetPowerLevel() == PhaserSystem.PP_LOW


def test_configure_phaser_high_power_by_default():
    inst, target = _build_fire_script_with_target()
    # bHighPower defaults to 1 in __init__.
    p = PhaserSystem("P")
    inst.ConfigureWeaponSystem(p, target, None)
    assert p.GetPowerLevel() == PhaserSystem.PP_HIGH


def test_configure_torpedo_default_does_not_call_choose_torp_type():
    """bChooseTorpsWisely defaults to 0 → ConfigureWeaponSystem
    returns 1 without invoking ChooseTorpType."""
    inst, target = _build_fire_script_with_target()
    t = TorpedoSystem("T")
    called = []
    original = inst.ChooseTorpType
    inst.ChooseTorpType = lambda *a, **kw: called.append(a)
    ok = inst.ConfigureWeaponSystem(t, target, None)
    assert ok == 1
    assert called == []


def test_configure_torpedo_with_smart_selection_calls_choose_torp_type():
    """bChooseTorpsWisely=1 → ChooseTorpType called with target location
    and target speed."""
    inst, target = _build_fire_script_with_target()
    inst.bChooseTorpsWisely = 1
    t = TorpedoSystem("T")
    called = []
    inst.ChooseTorpType = lambda *a, **kw: called.append(a)
    inst.ConfigureWeaponSystem(t, target, None)
    assert len(called) == 1


def test_configure_default_weapon_returns_one():
    """A weapon system that's not phaser/torp/tractor passes through
    as configured-OK without per-type setup."""
    from engine.appc.subsystems import WeaponSystem
    inst, target = _build_fire_script_with_target()
    w = WeaponSystem("Generic")
    ok = inst.ConfigureWeaponSystem(w, target, None)
    assert ok == 1
