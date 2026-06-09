from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty, TractorBeamProperty
from engine.appc.subsystems import TractorBeam
from engine.ui.ship_display_panel import _iter_damage_subsystems


def _build_ship_with_tractors():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    agg = WeaponSystemProperty("Tractors")
    agg.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    ps.AddToSet("Scene Root", agg)
    ps.AddToSet("Scene Root", TractorBeamProperty("Aft Tractor 1"))
    ps.AddToSet("Scene Root", TractorBeamProperty("Forward Tractor 1"))
    ship.SetupProperties()
    return ship


def test_tractor_aggregator_survives_with_children():
    # Records reality: the aggregator + emitters DO build (the finding's
    # "stays None" claim is incorrect).
    ship = _build_ship_with_tractors()
    assert ship.GetTractorBeamSystem() is not None
    assert ship.GetTractorBeamSystem().GetNumChildSubsystems() == 2


def test_tractor_subsystems_appear_in_damage_iteration():
    ship = _build_ship_with_tractors()
    names = {s.GetName() for s in _iter_damage_subsystems(ship)}
    assert "Tractors" in names
    assert "Aft Tractor 1" in names
    assert "Forward Tractor 1" in names
