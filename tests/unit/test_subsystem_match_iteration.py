"""Unit tests for ShipClass.StartGetSubsystemMatch with CT_WEAPON_SYSTEM
filter. SelectTarget's rating math walks weapon subsystems to compute
fWeaponsGood; the iterator must return them in stable order and
terminate cleanly."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    PhaserSystem, TorpedoSystem, PulseWeaponSystem, TractorBeamSystem,
)


def _drain_iter(ship, match_type):
    it = ship.StartGetSubsystemMatch(match_type)
    out = []
    sub = ship.GetNextSubsystemMatch(it)
    while sub is not None:
        out.append(sub)
        sub = ship.GetNextSubsystemMatch(it)
    ship.EndGetSubsystemMatch(it)
    return out


def test_no_filter_returns_empty():
    """Backward-compat: zero subsystems → iterator terminates without
    yielding anything."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()  # bare; no subsystems
    out = _drain_iter(ship, App.CT_WEAPON_SYSTEM)
    assert out == []


def test_weapon_filter_yields_phaser_torpedo_pulse_tractor():
    """ShipClass_Create allocates all 4 weapon subsystems; the filter
    yields them all."""
    ship = ShipClass_Create("Test")
    out = _drain_iter(ship, App.CT_WEAPON_SYSTEM)
    classes = {type(s) for s in out}
    assert PhaserSystem in classes
    assert TorpedoSystem in classes
    assert PulseWeaponSystem in classes
    assert TractorBeamSystem in classes


def test_weapon_filter_skips_non_weapon_subsystems():
    """Sensor / impulse / warp / shield / power / repair subsystems
    must NOT appear in a CT_WEAPON_SYSTEM iteration."""
    from engine.appc.subsystems import (
        SensorSubsystem, ImpulseEngineSubsystem,
        WarpEngineSubsystem, ShieldSubsystem,
        PowerSubsystem, RepairSubsystem,
    )
    ship = ShipClass_Create("Test")
    out = _drain_iter(ship, App.CT_WEAPON_SYSTEM)
    classes = {type(s) for s in out}
    for non_weapon in (SensorSubsystem, ImpulseEngineSubsystem,
                       WarpEngineSubsystem, ShieldSubsystem,
                       PowerSubsystem, RepairSubsystem):
        assert non_weapon not in classes


def test_iteration_terminates_after_drain():
    """After iterating all matches, GetNextSubsystemMatch returns
    None — required for SDK while-loops."""
    ship = ShipClass_Create("Test")
    it = ship.StartGetSubsystemMatch(App.CT_WEAPON_SYSTEM)
    while ship.GetNextSubsystemMatch(it) is not None:
        pass
    # Calling again must keep returning None.
    assert ship.GetNextSubsystemMatch(it) is None
    ship.EndGetSubsystemMatch(it)
