from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    EngineProperty, ImpulseEngineProperty, WarpEngineProperty,
)
from engine.appc.subsystems import ShipSubsystem


def _impulse_pod(name):
    p = EngineProperty(name)
    p.SetEngineType(EngineProperty.EP_IMPULSE)
    p.SetMaxCondition(2600.0)
    p.SetTargetable(1)
    p.SetRadius(0.25)
    return p


def _warp_pod(name):
    p = EngineProperty(name)
    p.SetEngineType(EngineProperty.EP_WARP)
    p.SetMaxCondition(5000.0)
    p.SetTargetable(1)
    return p


def test_impulse_pods_attach_to_impulse_aggregator():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", ImpulseEngineProperty("Impulse Engines"))
    for n in ("Port Impulse", "Star Impulse", "Center Impulse"):
        ps.AddToSet("Scene Root", _impulse_pod(n))
    ship.SetupProperties()

    imp = ship.GetImpulseEngineSubsystem()
    assert imp is not None
    assert imp.GetNumChildSubsystems() == 3
    child = imp.GetChildSubsystem("Port Impulse")
    assert isinstance(child, ShipSubsystem)
    assert child.GetMaxCondition() == 2600.0
    assert child.GetTargetable() == 1
    assert child.GetRadius() == 0.25


def test_warp_pods_attach_to_warp_aggregator():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", WarpEngineProperty("Warp Engines"))
    for n in ("Port Warp", "Star Warp"):
        ps.AddToSet("Scene Root", _warp_pod(n))
    ship.SetupProperties()

    warp = ship.GetWarpEngineSubsystem()
    assert warp is not None
    assert warp.GetNumChildSubsystems() == 2
    assert warp.GetChildSubsystem("Star Warp") is not None


def test_engine_pods_idempotent_on_rerun():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", ImpulseEngineProperty("Impulse Engines"))
    ps.AddToSet("Scene Root", _impulse_pod("Port Impulse"))
    ship.SetupProperties()
    ship.SetupProperties()  # must not double-attach
    assert ship.GetImpulseEngineSubsystem().GetNumChildSubsystems() == 1


def test_pods_dropped_when_aggregator_absent():
    # No ImpulseEngineProperty registered -> Pass 3 scrubs the aggregator to
    # None -> pods have no parent and are dropped (no fabricated engine).
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", _impulse_pod("Port Impulse"))
    ship.SetupProperties()  # must not raise
    assert ship.GetImpulseEngineSubsystem() is None
