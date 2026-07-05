"""Energy weapons (PhaserBank / PulseWeapon / TractorBeam) bill the
firing ship's PowerSubsystem each recharge tick.

Model: each charge unit refilled costs ``POWER_COST_PER_CHARGE`` power.
Per tick:

* `would_refill = recharge_rate * dt`, capped at headroom.
* `StealPower(would_refill * POWER_COST_PER_CHARGE)` — if it returns 0.0,
  no refill that tick (bank stays at current level).

Task 2 changed StealPower to drain main battery only (float return).
Tests now use main_battery as the power source for recharge billing.

Brings energy weapons in line with torpedoes: once the grid bottoms
out, banks stop recharging and fire stops as soon as the existing
charge depletes.  Test fixtures without a bound PowerProperty bypass
the gate, same convention as TorpedoTube.
"""
from unittest.mock import patch

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import PhaserBank, PhaserSystem, PowerSubsystem
from engine.appc.properties import PowerProperty


def _wire_phaser_bank(ship, *, with_power_property=True,
                       available=0.0, main_battery=0.0):
    """Build a PhaserSystem with one PhaserBank parented to ``ship``;
    bank starts mid-charge so UpdateCharge has headroom to refill."""
    system = PhaserSystem("Phasers")
    system.TurnOn()
    ship._phaser_system = system
    system._parent_ship = ship
    bank = PhaserBank("DorsalPhaser1")
    bank._max_charge = 5.0
    bank._min_firing_charge = 3.0
    bank._normal_discharge_rate = 1.0
    bank._recharge_rate = 0.08
    bank._charge_level = 4.0  # one unit of headroom
    system.AddChildSubsystem(bank)
    if with_power_property:
        ps = ship.GetPowerSubsystem()
        prop = PowerProperty("WarpCore")
        prop.SetPowerOutput(1000.0)
        prop.SetMainBatteryLimit(250000.0)
        ps.SetProperty(prop)
        ps.SetAvailablePower(available)
        ps.SetMainBatteryPower(main_battery)
    return bank


def test_recharge_proceeds_when_grid_has_power():
    """StealPower drains main battery (Task 2); put power there."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    before = bank._charge_level
    bank.UpdateCharge(1.0)  # 1 second; would refill by recharge_rate*dt = 0.08
    assert bank._charge_level > before
    assert abs(bank._charge_level - (before + 0.08)) < 1e-6


def test_recharge_bills_the_grid():
    """StealPower drains from main battery (Task 2 semantics)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank.UpdateCharge(1.0)  # 0.08 charge × 1.0 cost = 0.08 power
    ps = ship.GetPowerSubsystem()
    assert abs(ps.GetMainBatteryPower() - (100.0 - 0.08)) < 1e-6


def test_recharge_skips_when_grid_dry():
    """main battery zero → StealPower returns 0.0 (falsy) → bank stays put."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, available=0.0, main_battery=0.0)
    before = bank._charge_level
    bank.UpdateCharge(1.0)
    assert bank._charge_level == before


def test_recharge_falls_back_to_main_battery():
    """Main battery path unchanged — still drains main."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, available=0.0, main_battery=1000.0)
    before = bank._charge_level
    bank.UpdateCharge(1.0)
    assert bank._charge_level > before
    ps = ship.GetPowerSubsystem()
    assert abs(ps.GetMainBatteryPower() - (1000.0 - 0.08)) < 1e-6


def test_recharge_capped_at_max_charge_no_overcharge_billed():
    """Bank already at MaxCharge → no headroom → no refill billed."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank._charge_level = bank._max_charge
    bank.UpdateCharge(1.0)
    assert bank._charge_level == bank._max_charge
    ps = ship.GetPowerSubsystem()
    assert ps.GetMainBatteryPower() == 100.0


def test_recharge_billed_only_for_actual_refill_near_cap():
    """Headroom 0.05, would-be refill 0.08 → bill only the 0.05 actually used."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank._charge_level = bank._max_charge - 0.05
    bank.UpdateCharge(1.0)
    assert abs(bank._charge_level - bank._max_charge) < 1e-6
    ps = ship.GetPowerSubsystem()
    assert abs(ps.GetMainBatteryPower() - (100.0 - 0.05)) < 1e-6


def test_recharge_no_property_bypasses_gate():
    """Test fixture without a bound PowerProperty refills normally."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, with_power_property=False)
    before = bank._charge_level
    bank.UpdateCharge(1.0)
    assert bank._charge_level > before


def test_recharge_no_power_subsystem_bypasses_gate():
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, with_power_property=False)
    ship._power_subsystem = None
    before = bank._charge_level
    bank.UpdateCharge(1.0)
    assert bank._charge_level > before


def test_firing_discharge_not_gated_on_grid():
    """Discharge while firing represents pre-paid stored energy in the
    bank; it must not consult the grid (and must not be skipped when
    the grid is dry)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, available=0.0, main_battery=0.0)
    bank._charge_level = 5.0
    bank._firing = True
    bank.UpdateCharge(1.0)
    # Discharge proceeds: -normal_discharge_rate*dt = -1.0
    assert bank._charge_level < 5.0
