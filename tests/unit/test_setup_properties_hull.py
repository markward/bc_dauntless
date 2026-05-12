"""SetupProperties copies HullProperty identity fields onto the primary hull."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import HullProperty


def test_hull_property_propagation():
    ship = ShipClass_Create("Galaxy")
    h = HullProperty("Hull")
    h.SetMaxCondition(11000.0)
    h.SetCritical(0)
    h.SetTargetable(1)
    h.SetPrimary(1)
    h.SetRadius(1.0)
    h.SetDisabledPercentage(0.0)

    ship.GetPropertySet().AddToSet("Scene Root", h)
    ship.SetupProperties()

    hull = ship.GetHull()
    assert hull is not None
    assert hull.GetMaxCondition() == 11000.0
    assert hull.GetCondition() == 11000.0  # seeded full
    assert hull.GetCritical() == 0
    assert hull.GetTargetable() == 1
    assert hull.GetPrimary() == 1
    assert hull.GetDisabledPercentage() == 0.0


def test_hull_property_back_reference():
    """SDK mission code (E1M2 CreateDebris, E2M2 likewise) does
    ``pHull.GetProperty().SetMaxCondition(300.0)`` to override a
    pre-built asteroid's hull max at runtime.  SetupProperties must
    wire the back-reference so GetProperty() returns the source
    HullProperty, not None."""
    ship = ShipClass_Create("Asteroid")
    h = HullProperty("Asteroid")
    h.SetMaxCondition(2500.0)
    ship.GetPropertySet().AddToSet("Scene Root", h)
    ship.SetupProperties()

    hull = ship.GetHull()
    assert hull is not None
    assert hull.GetProperty() is h


def test_first_hull_wins():
    """Galaxy registers Hull then Bridge (both HullProperty). Primary hull
    should remain the first one."""
    ship = ShipClass_Create("Galaxy")
    primary = HullProperty("Hull")
    primary.SetMaxCondition(11000.0)
    secondary = HullProperty("Bridge")
    secondary.SetMaxCondition(500.0)

    ship.GetPropertySet().AddToSet("Scene Root", primary)
    ship.GetPropertySet().AddToSet("Scene Root", secondary)
    ship.SetupProperties()

    assert ship.GetHull().GetName() == "Hull"
    assert ship.GetHull().GetMaxCondition() == 11000.0
