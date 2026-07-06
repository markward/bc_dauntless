"""Energy weapons (PhaserBank / PulseWeapon / TractorBeam) — charge model
after Task 4b.

Task 4b decision: BC has no per-shot battery debit.  The continuous
NormalPowerPerSecond consumer draw (Task 4) covers energy cost.  PhaserBank
recharge is unconditional — UpdateCharge adds want to _charge_level directly
without calling the grid.

The old _bill_recharge helper that called StealPower on every recharge tick
has been removed.  Consequences:
  - Recharge always proceeds when the parent system is on and the bank has
    headroom, regardless of battery level.
  - The main battery is NOT touched by UpdateCharge.

Task 8 will make recharge rate power-factor-scaled; at factor 0 (fully
unpowered) the rate goes to 0 so banks stop recharging automatically.
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


def test_recharge_proceeds_when_system_on():
    """Recharge increments charge level unconditionally (no grid query)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    before = bank._charge_level
    bank.UpdateCharge(1.0)  # 1 second; would refill by recharge_rate*dt = 0.08
    assert bank._charge_level > before
    assert abs(bank._charge_level - (before + 0.08)) < 1e-6


def test_recharge_does_not_touch_battery():
    """UpdateCharge must NOT drain the main battery (no _bill_recharge)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank.UpdateCharge(1.0)
    ps = ship.GetPowerSubsystem()
    assert ps.GetMainBatteryPower() == 100.0


def test_recharge_proceeds_with_empty_battery():
    """Battery at zero — recharge still fills the bank (removed grid gate)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, available=0.0, main_battery=0.0)
    before = bank._charge_level
    bank.UpdateCharge(1.0)
    assert bank._charge_level > before


def test_recharge_capped_at_max_charge():
    """Bank already at MaxCharge → no headroom → charge level unchanged."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank._charge_level = bank._max_charge
    bank.UpdateCharge(1.0)
    assert bank._charge_level == bank._max_charge
    # Battery still untouched
    ps = ship.GetPowerSubsystem()
    assert ps.GetMainBatteryPower() == 100.0


def test_recharge_capped_near_max_charge():
    """Headroom 0.05, would-be refill 0.08 → only 0.05 added (cap logic)."""
    ship = ShipClass_Create("Test")
    bank = _wire_phaser_bank(ship, main_battery=100.0)
    bank._charge_level = bank._max_charge - 0.05
    bank.UpdateCharge(1.0)
    assert abs(bank._charge_level - bank._max_charge) < 1e-6
    # Battery untouched regardless of capping
    ps = ship.GetPowerSubsystem()
    assert ps.GetMainBatteryPower() == 100.0


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
