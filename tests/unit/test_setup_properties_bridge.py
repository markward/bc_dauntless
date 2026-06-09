from engine.appc.ships import ShipClass_Create
from engine.appc.properties import HullProperty
from engine.appc.subsystems import HullSubsystem


def _hull(name, primary, condition):
    p = HullProperty(name)
    p.SetPrimary(primary)
    p.SetTargetable(1)
    p.SetMaxCondition(condition)
    return p


def test_primary_hull_is_first_and_returned_by_get_hull():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()

    assert ship.GetHull().GetName() == "Hull"
    assert ship.GetHull().GetMaxCondition() == 15000.0


def test_bridge_is_a_child_of_the_primary_hull():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()

    hull = ship.GetHull()
    assert hull.GetNumChildSubsystems() == 1
    bridge = hull.GetChildSubsystem("Bridge")
    assert isinstance(bridge, HullSubsystem)
    assert bridge.GetMaxCondition() == 12000.0


def test_bridge_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _hull("Hull", 1, 15000.0))
    ps.AddToSet("Scene Root", _hull("Bridge", 0, 12000.0))
    ship.SetupProperties()
    ship.SetupProperties()
    assert ship.GetHull().GetNumChildSubsystems() == 1
