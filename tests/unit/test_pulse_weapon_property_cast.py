"""App.PulseWeaponProperty_Cast — heatmap ranks 83-88.

Conditions/ConditionPulseReady.py:139 does
`App.PulseWeaponProperty_Cast(pWeapon.GetProperty()).GetOrientationForward()`
and dots it against the wanted direction. A stub dots to 0, `0 >= 0.66` is
False, every weapon is excluded, lpCachedWeapons stays empty and the
condition reads FALSE forever — so every NonFedAttack ship
(NonFedAttack.py:272,545) never took its pulse-ready branch."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.properties import PulseWeaponProperty, ShieldProperty
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PulseWeaponSystem, PulseWeapon


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.PulseWeaponProperty_Cast, App._NamedStub)
    prop = PulseWeaponProperty("Cannon")
    assert App.PulseWeaponProperty_Cast(prop) is prop
    assert App.PulseWeaponProperty_Cast(ShieldProperty("S")) is None
    assert App.PulseWeaponProperty_Cast(None) is None


def test_condition_pulse_ready_sees_a_charged_forward_cannon():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)

    system = PulseWeaponSystem("Pulse")
    prop = PulseWeaponProperty("Cannon")
    prop.SetOrientation(App.TGPoint3_GetModelForward(), App.TGPoint3_GetModelUp())
    # ShipSubsystem.SetProperty (subsystems.py:369) mirrors position/
    # orientation/arc/damage fields onto the runtime subsystem but NOT the
    # charge fields (MaxCharge/MinFiringCharge) — see
    # tests/unit/test_pulse_weapon_fire.py's `_pulse_weapon` fixture, which
    # documents "Pass 4 copies property values onto runtime fields; do it
    # explicitly here." Same seeding needed here so GetChargeLevel() >
    # GetMinFiringCharge() is genuinely true rather than 0.0 > 0.0.
    prop.SetMaxCharge(3.8)
    prop.SetMinFiringCharge(3.6)
    cannon = PulseWeapon("Cannon")
    cannon.SetProperty(prop)
    cannon._max_charge = 3.8
    cannon._min_firing_charge = 3.6
    # AddChildSubsystem only wires _parent_subsystem, not _parent_ship
    # (subsystems.py:984) — set it explicitly, same as
    # tests/unit/test_phaser_bank_cast.py::_ship_with_forward_bank.
    cannon._parent_ship = ship
    system.AddChildSubsystem(cannon)
    # Real registration path: ShipClass.SetPulseWeaponSystem (ships.py:989),
    # which also attaches the parent ship — not a raw
    # `ship._pulse_weapon_system = system` assignment.
    ship.SetPulseWeaponSystem(system)
    pSet.AddObjectToSet(ship, "Ours")
    # Fully charged.
    cannon.SetChargeLevel(cannon.GetMaxCharge())

    cond = ConditionScript_Create(
        "Conditions.ConditionPulseReady", "ConditionPulseReady",
        "Ours", App.TGPoint3_GetModelForward())
    assert cond._instance is not None, cond._init_error
    assert len(cond._instance.lpCachedWeapons) == 1, (
        "the forward cannon was excluded — PulseWeaponProperty_Cast is a stub")
    assert cond.GetStatus() == 1
