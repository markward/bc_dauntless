"""Where a firing energy weapon's drain comes from — RE'd from stbc.exe
(docs/instrumented_experiments/2026-09-09-phaser-discharge-rate-source.md,
Findings Q-D1..Q-D5).

Three subclasses, three consumption models; the two we port here:

* PhaserBank — drains at a power-level TABLE (LOW 0.35 / MED 1.0 / HIGH
  1.0 charge-units per second, image 0x0089317c..0x00893184) indexed by the
  owning PhaserSystem's power level.  The hardpoint's NormalDischargeRate is
  never read on this path — a mod authoring 200.0 (CGSovereign) gets the
  same 1.0 s beam a stock ship gets.
* PulseWeapon — a flat per-shot cost of NormalDischargeRate × a power-setting
  scale (LOW 0.5 / MED 1.0 / HIGH 2.0) on the weapon's OWN PowerSetting,
  subtracted inside Fire.  Not a dump-to-zero: a stock BoP (3.8 tank, 3.6
  min, 0.4/s refill) is back on target ~2 s after a bolt, not ~9 s.

The two power fields are different objects: PhaserSystem.PowerLevel is the
system's; EnergyWeapon.PowerSetting is the emitter's.  Collapsing them is the
next bug of this shape.
"""
from unittest.mock import patch

import pytest

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    PhaserBank, PhaserSystem, PulseWeapon, PulseWeaponSystem,
)
from engine.appc.properties import PulseWeaponProperty, WeaponSystemProperty
from engine.appc.projectiles import _active


# ── PhaserBank: table, not property ──────────────────────────────────────────

def _cgsov_bank(power_level):
    """CGSovereign 'Ventral Phaser': MaxCharge 1.0, MinFiringCharge 1.0,
    NormalDischargeRate 200.0 — the authored rate that would empty the tank
    in 5 ms if it were read."""
    bank = PhaserBank("Ventral Phaser")
    parent = PhaserSystem("Phasers")
    parent.TurnOn()
    parent.SetPowerLevel(power_level)
    parent.AddChildSubsystem(bank)
    bank._max_charge = 1.0
    bank._min_firing_charge = 1.0
    bank._charge_level = 1.0
    bank._recharge_rate = 0.4
    bank._normal_discharge_rate = 200.0
    return bank


@pytest.mark.parametrize("level, expected_after_half_second", [
    (PhaserSystem.PP_LOW, 1.0 - 0.35 * 0.5),
    (PhaserSystem.PP_MEDIUM, 1.0 - 1.0 * 0.5),
    (PhaserSystem.PP_HIGH, 1.0 - 1.0 * 0.5),
])
def test_phaser_drain_is_the_power_table_not_the_authored_rate(
        level, expected_after_half_second):
    bank = _cgsov_bank(level)
    assert bank.Fire(target=None, offset=None)
    bank._beam_on_countdown = 0.0     # past the 0.66 s beam-on delay (oracle B6)
    bank.UpdateCharge(dt=0.5)
    assert bank.GetChargeLevel() == pytest.approx(expected_after_half_second)
    assert bank.IsFiring() == 1


def test_phaser_authored_rate_is_still_readable():
    """The property is stored and exposed (it is live for PulseWeapon);
    only the phaser drain path ignores it."""
    bank = _cgsov_bank(PhaserSystem.PP_HIGH)
    assert bank.GetNormalDischargeRate() == 200.0


def test_phaser_still_stops_on_the_update_that_empties_it():
    """Q-D7: exhaustion stops the beam on the same update, no interval."""
    bank = _cgsov_bank(PhaserSystem.PP_HIGH)
    assert bank.Fire(target=None, offset=None)
    bank._beam_on_countdown = 0.0     # past the beam-on delay
    bank.UpdateCharge(dt=1.0)
    assert bank.GetChargeLevel() == 0.0
    assert bank.IsFiring() == 0


# ── PulseWeapon: per-shot cost × PowerSetting ────────────────────────────────

_MODULE = "Tactical.Projectiles.PulseDisruptor"


def _bop_cannon():
    """BoP PortCannon: MaxCharge 3.8, MinFiringCharge 3.6, RechargeRate 0.4,
    NormalDischargeRate 1.0, CooldownTime 0.2 (stock birdofprey.py)."""
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    parent = PulseWeaponSystem("Pulse")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Pulse"))
    parent._parent_ship = ship
    ship._pulse_weapon_system = parent

    cannon = PulseWeapon("Port Cannon")
    prop = PulseWeaponProperty("Port Cannon")
    prop.SetMaxCharge(3.8)
    prop.SetMinFiringCharge(3.6)
    prop.SetRechargeRate(0.4)
    prop.SetNormalDischargeRate(1.0)
    prop.SetCooldownTime(0.2)
    prop.SetMaxDamage(200.0)
    prop.SetModuleName(_MODULE)
    cannon.SetProperty(prop)
    cannon._max_charge = 3.8
    cannon._min_firing_charge = 3.6
    cannon._recharge_rate = 0.4
    cannon._normal_discharge_rate = 1.0
    cannon._cooldown_time = 0.2
    cannon._charge_level = 3.8
    parent.AddChildSubsystem(cannon)
    return cannon


def _fire(cannon):
    """One bolt at a real target 100 GU dead ahead — the targeted fire path
    resolves an aim point on it and refuses anything it cannot (BC slot
    +0x7C), so a bare string no longer stands in for a target."""
    enemy = ShipClass_Create("Enemy")
    enemy.SetWorldLocation(TGPoint3(0, 100, 0))
    _active.clear()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        fired = cannon.Fire(target=enemy, offset=TGPoint3(0, 0, 0))
    _active.clear()
    return fired


def test_pulse_power_setting_defaults_to_medium():
    """ASSUMED, not RE'd: the SDK never calls SetPowerSetting, and the RE
    answer did not give the constructor value.  MED (×1.0) is the neutral
    choice; if a later read of the constructor says otherwise, change this
    default and this test together."""
    cannon = _bop_cannon()
    assert cannon.GetPowerSetting() == 1


@pytest.mark.parametrize("setting, expected_after_shot", [
    (0, 3.8 - 1.0 * 0.5),   # LOW
    (1, 3.8 - 1.0 * 1.0),   # MED
    (2, 3.8 - 1.0 * 2.0),   # HIGH
])
def test_pulse_shot_costs_authored_rate_times_power_scale(
        setting, expected_after_shot):
    cannon = _bop_cannon()
    cannon.SetPowerSetting(setting)
    assert _fire(cannon)
    assert cannon.GetChargeLevel() == pytest.approx(expected_after_shot)


def test_pulse_shot_cost_floors_at_zero():
    """A bolt that costs exactly the stored charge fires and leaves 0."""
    cannon = _bop_cannon()
    cannon._normal_discharge_rate = 3.8
    assert _fire(cannon)
    assert cannon.GetChargeLevel() == 0.0


def test_pulse_cannot_fire_a_bolt_it_cannot_afford():
    """The fire gate is affordability — charge ≥ the per-shot cost — not
    MinFiringCharge (stbc-oracle `pulse_warbird_front_40_*`, `pulse_bop_
    front_40`: cannons fire well below MinFiringCharge and stop exactly when
    the next bolt's cost exceeds the charge)."""
    cannon = _bop_cannon()
    cannon._normal_discharge_rate = 50.0
    assert cannon.CanFire() == 0
    assert not _fire(cannon)
    assert cannon.GetChargeLevel() == pytest.approx(3.8)


def test_pulse_refire_cadence_is_seconds_not_a_full_refill():
    """The gameplay consequence: after one bolt at MED (cost 1.0) the BoP
    can afford the next as soon as it has 1.0 again — it never needs a full
    refill (3.6 / 0.4 = 9.0 s); measured, it fires four in a row."""
    cannon = _bop_cannon()
    assert _fire(cannon)
    for _ in range(20):          # 2.0 s at 0.1 s steps (cooldown 0.2 s expires)
        cannon.UpdateCharge(dt=0.1)
    assert cannon.GetChargeLevel() == pytest.approx(3.6)
    assert cannon.CanFire() == 1


def test_pulse_power_setting_is_not_the_phaser_power_level():
    """Two fields, two owners.  Setting the ship's PhaserSystem power level
    must not move a pulse cannon's own PowerSetting."""
    cannon = _bop_cannon()
    phasers = PhaserSystem("Phasers")
    phasers.SetPowerLevel(PhaserSystem.PP_LOW)
    assert cannon.GetPowerSetting() == 1
