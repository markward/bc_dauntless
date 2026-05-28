"""SetupProperties dispatches PowerProperty -> _power_subsystem and
RepairSubsystemProperty -> _repair_subsystem, copying MaxCondition
through and setting the property back-reference."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import PowerProperty, RepairSubsystemProperty


def test_setup_properties_wires_power_plant():
    ship = ShipClass_Create("DryDock")
    p = PowerProperty("Power Plant")
    p.SetMaxCondition(2000.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    power = ship.GetPowerSubsystem()
    assert power is not None
    assert power.GetProperty() is p
    assert power.GetMaxCondition() == 2000.0


def test_setup_properties_wires_engineering():
    ship = ShipClass_Create("DryDock")
    r = RepairSubsystemProperty("Engineering")
    r.SetMaxCondition(1500.0)
    r.SetNormalPowerPerSecond(40.0)
    ship.GetPropertySet().AddToSet("Scene Root", r)
    ship.SetupProperties()

    repair = ship.GetRepairSubsystem()
    assert repair is not None
    assert repair.GetProperty() is r
    assert repair.GetMaxCondition() == 1500.0
    # RepairSubsystem inherits PoweredSubsystem -> picks up power line.
    assert repair.GetNormalPowerPerSecond() == 40.0


def test_setup_properties_initializes_battery_pools_from_property_limits():
    """The PowerProperty carries the hardpoint-declared MainBatteryLimit
    + BackupBatteryLimit (Galaxy WarpCore: 250000 / 80000).  After
    SetupProperties the PowerSubsystem should start with batteries full
    so a fresh ship can fire / shield before the first per-tick refill."""
    ship = ShipClass_Create("DryDock")
    p = PowerProperty("Power Plant")
    p.SetPowerOutput(1000.0)
    p.SetMainBatteryLimit(250000.0)
    p.SetBackupBatteryLimit(80000.0)
    p.SetMainConduitCapacity(1200.0)
    p.SetBackupConduitCapacity(200.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    power = ship.GetPowerSubsystem()
    assert power.GetMainBatteryPower() == 250000.0
    assert power.GetBackupBatteryPower() == 80000.0


def test_setup_properties_power_repair_survive_scrub_only_when_property_set():
    """Pass 3 only scrubs slots whose GetProperty() is None.  When
    PowerProperty is in the set, the slot survives."""
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", PowerProperty("Power Plant"))
    ship.SetupProperties()
    assert ship.GetPowerSubsystem() is not None
    assert ship.GetRepairSubsystem() is None
