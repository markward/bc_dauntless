"""A FireScript with an explicit TargetSubsystems list (every Disable order:
AI/Fleet/DisableTarget.py:18, AI/Player/Disable*.py) reaches
Preprocessors.py:832 `self.GetChildTargets(pSubsystem)` whenever the matched
subsystem is non-targetable — and stock hardpoints mark Impulse/Warp/
Phasers/Torpedoes/Tractors/Engineering SetTargetable(0)
(ships/Hardpoints/galaxy.py:774-995). GetChildTargets is defined nowhere
in the SDK: it was a method of BC's NATIVE FireScript. Reproduced 2026-09-19
as an AttributeError out of tick_ai after ~0.8 s."""
import pytest

import App
from engine.appc import ai_sensor_gate
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (HullSubsystem, ImpulseEngineSubsystem,
                                    SensorSubsystem, TorpedoAmmoType)
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _reset_app_state()
    monkeypatch.setattr(ai_sensor_gate, "can_detect", lambda *a, **k: True)
    yield
    _reset_app_state()


def _scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # Real setters, not private-attribute pokes: GetPhaserSystem/
    # GetTorpedoSystem/etc. read the _attach_subsystem-populated slots, not
    # a bare `_phaser`/`_torpedo_system` assignment (engine/appc/ships.py:979-987).
    ours.SetImpulseEngineSubsystem(ImpulseEngineSubsystem("IES"))
    ours.GetImpulseEngineSubsystem().SetMaxSpeed(120.0)
    ours.SetSensorSubsystem(SensorSubsystem("Sensors"))
    ours.SetPhaserSystem(PhaserSystem("P"))
    ours.SetTorpedoSystem(TorpedoSystem("T"))
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")

    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    # The galaxy.py shape: a non-targetable aggregator with targetable children.
    phasers = PhaserSystem("Phasers")
    phasers.SetTargetable(0)
    bank = PhaserBank("Fwd Bank"); bank._parent_ship = target
    bank.SetMaxCondition(100.0); bank.SetCondition(100.0); bank.SetTargetable(1)
    phasers.AddChildSubsystem(bank)  # wires bank._parent_subsystem = phasers
    target.SetPhaserSystem(phasers)
    pSet.AddObjectToSet(target, "Target")
    ours.SetTarget("Target")

    # Confirm the SDK's iteration path (ChooseTargetSubsystem ->
    # StartGetSubsystemMatch(CT_WEAPON_SYSTEM)) actually yields the phaser
    # system -- otherwise this whole test is vacuous.
    matched = list(target.StartGetSubsystemMatch(App.CT_WEAPON_SYSTEM))
    assert phasers in matched, matched

    return ours, target, bank


def _disable_fire_script(ours):
    import AI.Preprocessors
    pFire = PreprocessingAI_Create(ours, "Fire")
    fs = AI.Preprocessors.FireScript("Target", TargetSubsystems=[(App.CT_WEAPON_SYSTEM, 1)])
    pFire.SetPreprocessingMethod(fs, "Update")
    inst = pFire.GetPreprocessingInstance()
    inst.AddWeaponSystem(ours._torpedo_system); inst.AddWeaponSystem(ours._phaser_system)
    pStay = PlainAI_Create(ours, "Stay"); pStay.SetScriptModule("Stay")
    pFire.SetContainedAI(pStay)
    ours.SetAI(pFire)
    return pFire


def test_get_child_targets_returns_targetable_live_descendants():
    ours, target, bank = _scene()
    pFire = _disable_fire_script(ours)
    inst = pFire.GetPreprocessingInstance()
    assert inst.GetChildTargets(target._phaser_system) == [bank]
    bank.SetCondition(0.0)
    assert inst.GetChildTargets(target._phaser_system) == []


def test_disable_order_runs_ten_seconds_and_picks_a_subsystem():
    ours, target, bank = _scene()
    pFire = _disable_fire_script(ours)
    t = 0.0
    for _ in range(600):
        tick_ai(pFire, t); t += 1.0 / 60
    assert pFire._last_script_error is None, pFire._last_script_error
    assert ours.GetTargetSubsystem() is not None, (
        "Disable order never chose a subsystem to fire at")
