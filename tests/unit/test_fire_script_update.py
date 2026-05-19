"""FireScript.Update cycle: -2 (visibility), -1 (subsystem), 0..N-1 (fire).

SDK Preprocessors.py:281-342 — main per-tick driver. With N=2 weapons,
the iLastUpdate counter cycles -2, -1, 0, 1, -2, -1, 0, 1, ...

Default config has bChooseSubsystemTargets=0 and no TargetSubsystems list,
so ChooseTargetSubsystem returns None and FireScript fires at center mass."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, PhaserSystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 100, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_fire_script(ours, *weapons):
    from AI.Preprocessors import FireScript
    inst = FireScript("Target")
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp
    pp.SetPreprocessingMethod(inst, "Update")
    for w in weapons:
        inst.AddWeaponSystem(w)
    return inst, pp


def test_update_with_no_weapons_returns_normal():
    ours, _target = _build_scene()
    inst, pp = _wire_fire_script(ours)
    result = inst.Update(dEndTime=999.0)
    assert result == App.PreprocessingAI.PS_NORMAL


def test_update_with_no_target_returns_done():
    """sTarget resolves to None → PS_DONE."""
    ours, _target = _build_scene()
    inst, pp = _wire_fire_script(ours, PhaserSystem("P"))
    inst.sTarget = "NoSuchShip"
    result = inst.Update(dEndTime=999.0)
    assert result == App.PreprocessingAI.PS_DONE


def test_update_disabled_returns_normal_without_firing():
    """bEnabled=0 → PS_NORMAL without invoking StartFiring."""
    ours, _target = _build_scene()
    p = PhaserSystem("P")
    inst, pp = _wire_fire_script(ours, p)
    inst.bEnabled = 0
    # Force past the visibility branch.
    inst.bTargetVisible = 1
    inst.iLastUpdate = 0
    fired = []
    p.StartFiring = lambda t, o: fired.append((t, o))
    inst.Update(dEndTime=999.0)
    assert fired == []


def test_update_first_tick_is_visibility_frame():
    """iLastUpdate starts at -1 in __init__, but the first tick enters
    the (not bTargetVisible) branch which calls TargetVisible (which sets
    bTargetVisible=1 in the SDK stub). After the call, iLastUpdate is
    either still in the visibility branch or has advanced. We assert
    bTargetVisible flipped to 1."""
    ours, _target = _build_scene()
    inst, pp = _wire_fire_script(ours, PhaserSystem("P"))
    assert inst.bTargetVisible == 0
    inst.Update(dEndTime=999.0)
    assert inst.bTargetVisible == 1


def test_update_subsequent_tick_fires_a_weapon():
    """After visibility flips, FireScript advances iLastUpdate and starts
    firing weapons in round-robin. With N=2 weapons, ticks 2 and 3 should
    each invoke StartFiring once."""
    ours, _target = _build_scene()
    p1, p2 = PhaserSystem("P1"), PhaserSystem("P2")
    inst, pp = _wire_fire_script(ours, p1, p2)
    fired = []
    p1.StartFiring = lambda t, o: fired.append(("P1", t))
    p2.StartFiring = lambda t, o: fired.append(("P2", t))

    # 4 ticks: -2 (visibility), -1 (subsystem), 0 (fire P1), 1 (fire P2).
    for _ in range(4):
        inst.Update(dEndTime=999.0)
    weapons_fired = [name for name, _ in fired]
    assert "P1" in weapons_fired
    assert "P2" in weapons_fired
