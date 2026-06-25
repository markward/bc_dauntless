"""PulseWeapon.Fire — discrete projectile bolt (NOT a held beam).

BC pulse weapons (disruptors/cannons) fire discrete projectile shots, unlike
phasers/tractors which hold a beam.  Fire spawns one bolt via the bound
PulseDisruptor module, dumps all accumulated charge, and starts a per-shot
cooldown timer.  No looping SFX; the launch sound comes from the module.

Charge model from sdk/Build/scripts/ships/Hardpoints/birdofprey.py PortCannon:
MaxCharge 3.8, MinFiringCharge 3.6, RechargeRate 0.4/s, NormalDischargeRate
1.0/s, SetCooldownTime(0.2), MaxDamage 200, ModuleName
"Tactical.Projectiles.PulseDisruptor".  The module: PowerCost=10, Damage=220,
Lifetime=8.0, LaunchSpeed=55, LaunchSound="Klingon Disruptor".
"""
from unittest.mock import patch

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import PulseWeapon, PulseWeaponSystem
from engine.appc.properties import (
    PulseWeaponProperty, WeaponSystemProperty, PowerProperty,
)
from engine.appc.projectiles import _active

_MODULE = "Tactical.Projectiles.PulseDisruptor"


def _pulse_weapon(*, module_name=_MODULE, with_power_property=False,
                  available=0.0, main_battery=0.0):
    """Build a PulseWeapon under a powered PulseWeaponSystem on a ship.

    Seeds the cannon's charge fields to the BoP PortCannon values and fills
    charge to MaxCharge so CanFire is true.  Optionally binds a PowerProperty
    so the per-shot power gate engages.  Returns the PulseWeapon.
    """
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    parent = PulseWeaponSystem("Pulse")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Pulse")
    parent.SetProperty(parent_prop)
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
    prop.SetModuleName(module_name)
    cannon.SetProperty(prop)
    # Pass-4 copies property values onto runtime fields; do it explicitly here.
    cannon._max_charge = 3.8
    cannon._min_firing_charge = 3.6
    cannon._recharge_rate = 0.4
    cannon._normal_discharge_rate = 1.0
    cannon._cooldown_time = 0.2
    cannon._charge_level = 3.8  # MaxCharge -> CanFire true
    parent.AddChildSubsystem(cannon)

    if with_power_property:
        ps = ship.GetPowerSubsystem()
        pwr = PowerProperty("WarpCore")
        pwr.SetPowerOutput(1000.0)
        pwr.SetMainBatteryLimit(250000.0)
        ps.SetProperty(pwr)
        ps.SetAvailablePower(available)
        ps.SetMainBatteryPower(main_battery)

    return cannon


# ── Spawn / charge / cooldown ───────────────────────────────────────────────

def test_fire_spawns_one_bolt_with_module_payload():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert len(_active) == 1
    bolt = _active[-1]
    assert bolt._damage == 220.0
    assert bolt._guidance_lifetime == 0.0
    assert bolt._ttl == 8.0
    _active.clear()


def test_fire_dumps_charge_and_starts_cooldown():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert cannon._charge_level == 0.0
    assert cannon._cooldown_remaining == 0.2
    assert cannon.CanFire() == 0
    _active.clear()


def test_second_immediate_fire_is_no_op():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
        assert len(_active) == 1
        cannon.Fire(target="enemy", offset="hit")
    # Cooldown active -> CanFire 0 -> no new bolt.
    assert len(_active) == 1
    _active.clear()


def test_fire_does_not_set_firing_or_loop_handle():
    """Pulse weapons are discrete; Fire must not hold a beam."""
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert cannon._firing is False
    assert cannon._loop_handle is None
    _active.clear()


# ── UpdateCharge: cooldown decay + recharge (never discharge) ────────────────

def test_update_charge_decrements_cooldown():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    cannon.UpdateCharge(dt=0.1)
    assert abs(cannon._cooldown_remaining - 0.1) < 1e-9
    cannon.UpdateCharge(dt=0.2)  # past the 0.2 cooldown total
    assert cannon._cooldown_remaining == 0.0
    _active.clear()


def test_update_charge_recharges_never_discharges():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    # Charge dumped to 0; recharge fills it (firing stays False).
    cannon.UpdateCharge(dt=1.0)
    assert cannon._charge_level > 0.0
    assert cannon._charge_level == 0.4  # recharge_rate 0.4 * 1.0s
    _active.clear()


# ── Module-name guards ──────────────────────────────────────────────────────

def test_fire_empty_module_name_silent_no_op():
    _active.clear()
    cannon = _pulse_weapon(module_name="")
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")  # must not raise
    assert len(_active) == 0
    # Charge not dumped, no cooldown started.
    assert cannon._charge_level == 3.8
    assert cannon._cooldown_remaining == 0.0
    _active.clear()


# ── Power gate ──────────────────────────────────────────────────────────────

def test_fire_silent_no_op_when_power_insufficient():
    _active.clear()
    cannon = _pulse_weapon(with_power_property=True, available=5.0, main_battery=0.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert len(_active) == 0
    # Charge NOT drained, no cooldown started.
    assert cannon._charge_level == 3.8
    assert cannon._cooldown_remaining == 0.0
    _active.clear()


def test_fire_succeeds_when_power_covers_cost():
    _active.clear()
    cannon = _pulse_weapon(with_power_property=True, available=100.0, main_battery=0.0)
    ship = cannon._climb_to_ship()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert len(_active) == 1
    # PowerCost 10 drained from available.
    assert ship.GetPowerSubsystem().GetAvailablePower() == 90.0
    _active.clear()


def test_fire_without_power_property_bypasses_gate():
    _active.clear()
    cannon = _pulse_weapon(with_power_property=False)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        cannon.Fire(target="enemy", offset="hit")
    assert len(_active) == 1
    _active.clear()


# ── Launch sound ────────────────────────────────────────────────────────────

def test_fire_plays_launch_sound():
    _active.clear()
    cannon = _pulse_weapon()
    with patch("engine.audio.tg_sound.TGSoundManager.instance") as mock_mgr:
        cannon.Fire(target="enemy", offset="hit")
        mock_mgr.return_value.PlaySound.assert_called_with("Klingon Disruptor")
    _active.clear()
