"""Phaser, pulse and tractor banks answer the Weapon AI surface.

BC's PhaserBank, PulseWeapon and TractorBeam are Weapons, so the SDK calls
Weapon::CalculateRoughDirection and Weapon::CalculateWeaponAppeal on them.
Ours derive from WeaponSystem instead of Weapon, so both fell through to a
truthy _Stub. The SDK's IntelligentCircleObject (FedAttack's "circle with
weapons" move) dots that stub to 0 on every axis and files every phaser bank
as pointing straight out the starboard side; a QuickBattle export of three
Akiras showed all of them parked at the same angle, phasers not bearing.
PhaserSweep's arc check reads the same stub (448 hits in that run).
"""
import math

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import PhaserSystem, PulseWeaponSystem, TractorBeamSystem
from engine.appc.weapon_subsystems import PhaserBank, PulseWeapon, TractorBeam


def _mount(system_cls, setter, bank_cls, direction, yaw=0.0):
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    if yaw:
        ship.SetMatrixRotation(TGMatrix3().MakeZRotation(yaw))
    system = system_cls("System")
    system.TurnOn()
    getattr(ship, setter)(system)
    bank = bank_cls("Bank")
    bank.SetDirection(TGPoint3(*direction))
    bank._max_condition = 100.0
    bank._condition = 100.0
    system.AddChildSubsystem(bank)
    return ship, bank


_KINDS = [
    (PhaserSystem, "SetPhaserSystem", PhaserBank),
    (PulseWeaponSystem, "SetPulseWeaponSystem", PulseWeapon),
    (TractorBeamSystem, "SetTractorBeamSystem", TractorBeam),
]


def _xyz(p):
    return [round(p.x, 6), round(p.y, 6), round(p.z, 6)]


@pytest.mark.parametrize("system_cls,setter,bank_cls", _KINDS)
def test_rough_direction_is_the_mount_direction_in_world_space(system_cls, setter, bank_cls):
    # Port-facing bank (model -X) on a ship yawed 90 degrees about Z: the
    # column-vector rotation takes model -X to world -Y.
    _, bank = _mount(system_cls, setter, bank_cls, (-1.0, 0.0, 0.0), yaw=math.pi / 2)
    v = bank.CalculateRoughDirection()
    assert isinstance(v, TGPoint3)
    assert _xyz(v) == pytest.approx([0.0, -1.0, 0.0], abs=1e-6)


@pytest.mark.parametrize("system_cls,setter,bank_cls", _KINDS)
def test_weapon_appeal_is_a_number_and_zero_when_disabled(system_cls, setter, bank_cls):
    _, bank = _mount(system_cls, setter, bank_cls, (1.0, 0.0, 0.0))
    assert bank.CalculateWeaponAppeal() == 1.0
    bank._condition = 0.0
    assert bank.IsDisabled()
    assert bank.CalculateWeaponAppeal() == 0.0


def test_circle_object_files_a_port_phaser_on_the_port_side():
    """The SDK's own maths, fed a real bank: a port-facing phaser must land at
    -90 degrees (port), not the +90 (starboard) every bank got from the stub."""
    import App
    from AI.PlainAI.IntelligentCircleObject import IntelligentCircleObject

    ship, bank = _mount(PhaserSystem, "SetPhaserSystem", PhaserBank, (-1.0, 0.0, 0.0))
    world_to_model = ship.GetWorldRotation().Transpose()
    v, value = IntelligentCircleObject.GetWeaponDirectionAndValue(None, bank, world_to_model)

    up = App.TGPoint3_GetModelUp().Dot(v)
    right = App.TGPoint3_GetModelRight().Dot(v)
    angle = math.acos(up)
    if right < 0:
        angle = -angle
    assert angle == pytest.approx(-math.pi / 2)
    assert value == 1.0
