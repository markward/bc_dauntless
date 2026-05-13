"""Tests for ShipClass.GetPropertySet / SetupProperties — the bridge that
copies hardpoint template values (mass, MaxSpeed, etc.) onto the live ship
and its live subsystems.

Mirrors SDK loadspacehelper.py:87-94 — pShip.GetPropertySet() returns a
real TGModelPropertySet, then mod.LoadPropertySet(pPropertySet) populates
it, and pShip.SetupProperties() walks it to plumb fields onto the live
subsystem instances.
"""

from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.properties import (
    TGModelPropertySet,
    ShipProperty,
    ImpulseEngineProperty,
    WarpEngineProperty,
    HullProperty,
)


# ── Cycle A: GetPropertySet returns a real TGModelPropertySet ─────────────────

def test_ship_get_property_set_returns_real_set():
    ship = ShipClass()
    ps = ship.GetPropertySet()
    assert isinstance(ps, TGModelPropertySet)


def test_ship_get_property_set_returns_same_instance():
    ship = ShipClass()
    assert ship.GetPropertySet() is ship.GetPropertySet()


# ── Cycle B: Typed getters/setters on subsystems ──────────────────────────────
# Mirrors SDK App.py:6689-6692 (ImpulseEngineSubsystem) and the SetMaxCondition
# pattern shared by every ShipSubsystem.

def test_impulse_subsystem_max_speed_default_zero():
    from engine.appc.subsystems import ImpulseEngineSubsystem
    s = ImpulseEngineSubsystem()
    assert s.GetMaxSpeed() == 0.0


def test_impulse_subsystem_max_speed_round_trip():
    from engine.appc.subsystems import ImpulseEngineSubsystem
    s = ImpulseEngineSubsystem()
    s.SetMaxSpeed(6.3)
    assert s.GetMaxSpeed() == 6.3


def test_impulse_subsystem_max_accel_round_trip():
    from engine.appc.subsystems import ImpulseEngineSubsystem
    s = ImpulseEngineSubsystem()
    s.SetMaxAccel(1.5)
    assert s.GetMaxAccel() == 1.5


def test_impulse_subsystem_max_angular_velocity_round_trip():
    from engine.appc.subsystems import ImpulseEngineSubsystem
    s = ImpulseEngineSubsystem()
    s.SetMaxAngularVelocity(0.28)
    assert s.GetMaxAngularVelocity() == 0.28


def test_impulse_subsystem_max_angular_accel_round_trip():
    from engine.appc.subsystems import ImpulseEngineSubsystem
    s = ImpulseEngineSubsystem()
    s.SetMaxAngularAccel(0.12)
    assert s.GetMaxAngularAccel() == 0.12


def test_subsystem_set_max_condition_round_trip():
    from engine.appc.subsystems import ShipSubsystem
    s = ShipSubsystem()
    s.SetMaxCondition(2400.0)
    assert s.GetMaxCondition() == 2400.0


def test_set_max_condition_seeds_current_condition_when_default():
    """SDK semantics (App.py:5601): SetMaxCondition on a fresh subsystem also
    seeds the current condition to full so freshly-loaded ships start undamaged."""
    from engine.appc.subsystems import ShipSubsystem
    s = ShipSubsystem()
    assert s.GetCondition() == 1.0  # default
    s.SetMaxCondition(2400.0)
    assert s.GetCondition() == 2400.0


# ── Cycle C: SetupProperties dispatcher ────────────────────────────────────────
# Walks the ship's PropertySet and copies template values onto the live ship
# and its live subsystems. Mirrors SDK loadspacehelper.py:94 (pShip.SetupProperties()).

def _galaxy_like_ship_property():
    """A ShipProperty matching galaxy.py:1119-1133 values."""
    p = ShipProperty("Galaxy")
    p.SetMass(120.0)
    p.SetRotationalInertia(15000.0)
    return p


def _galaxy_like_impulse_property():
    """An ImpulseEngineProperty matching galaxy.py:772-786 values."""
    p = ImpulseEngineProperty("Impulse Engines")
    p.SetMaxCondition(2400.0)
    p.SetMaxSpeed(6.3)
    p.SetMaxAccel(1.5)
    p.SetMaxAngularVelocity(0.28)
    p.SetMaxAngularAccel(0.12)
    p.SetNormalPowerPerSecond(150.0)
    return p


def test_setup_properties_copies_ship_mass():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", _galaxy_like_ship_property())
    ship.SetupProperties()
    assert ship.GetMass() == 120.0


def test_setup_properties_copies_ship_rotational_inertia():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", _galaxy_like_ship_property())
    ship.SetupProperties()
    assert ship.GetRotationalInertia() == 15000.0


def test_setup_properties_copies_impulse_engine_fields():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", _galaxy_like_impulse_property())
    ship.SetupProperties()
    ies = ship.GetImpulseEngineSubsystem()
    assert ies.GetMaxSpeed() == 6.3
    assert ies.GetMaxAccel() == 1.5
    assert ies.GetMaxAngularVelocity() == 0.28
    assert ies.GetMaxAngularAccel() == 0.12
    assert ies.GetMaxCondition() == 2400.0
    assert ies.GetNormalPowerPerSecond() == 150.0


def test_setup_properties_copies_warp_engine_fields():
    ship = ShipClass_Create("Galaxy")
    p = WarpEngineProperty("Warp Engines")
    p.SetMaxCondition(500.0)
    p.SetNormalPowerPerSecond(200.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    wes = ship.GetWarpEngineSubsystem()
    assert wes.GetMaxCondition() == 500.0
    assert wes.GetNormalPowerPerSecond() == 200.0


def test_setup_properties_creates_hull_subsystem_from_property():
    """HullProperty -> live HullSubsystem accessible via ship.GetHull(),
    mirroring SDK App.py:5382-5383."""
    ship = ShipClass_Create("Galaxy")
    p = HullProperty("Hull")
    p.SetMaxCondition(15000.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    hull = ship.GetHull()
    assert hull is not None
    assert hull.GetMaxCondition() == 15000.0


def test_setup_properties_no_op_when_property_set_empty():
    """SetupProperties on a ship with no templates must not raise.  With
    no hardpoint-registered properties, every pre-allocated subsystem
    slot is scrubbed (Pass 3) and Hull stays None as it never auto-creates."""
    ship = ShipClass_Create("blank")
    ship.SetupProperties()  # must not raise
    assert ship.GetMass() == 0.0
    assert ship.GetHull() is None
    assert ship.GetImpulseEngineSubsystem() is None
    assert ship.GetWarpEngineSubsystem() is None
    assert ship.GetSensorSubsystem() is None
    assert ship.GetShieldSubsystem() is None
    assert ship.GetPhaserSystem() is None
    assert ship.GetTorpedoSystem() is None
    assert ship.GetPulseWeaponSystem() is None
    assert ship.GetTractorBeamSystem() is None
    assert ship.GetPowerSubsystem() is None
    assert ship.GetRepairSubsystem() is None


# ── Cycle D: SDK reload() must re-execute module top-level ────────────────────
# loadspacehelper.CreateShip (SDK) clears local templates then calls reload(mod)
# to re-register them.  If the harness stubs reload to a no-op, templates stay
# cleared and FindByName returns None for every property — the silent failure
# mode that produced the original "MaxSpeed returns None" symptom.

def test_sdk_module_reload_is_real_importlib_reload():
    import importlib
    import loadspacehelper  # mission_harness installs SDK importer
    assert loadspacehelper.reload is importlib.reload


# ── Cycle E: end-to-end integration with loadspacehelper.CreateShip ───────────

# ── Cycle F: App.CT_* property-type constants are real classes ───────────────
# loadspacehelper.AdjustShipForDifficulty (and MissionLib) call
# pSet.GetPropertiesByType(App.CT_SUBSYSTEM_PROPERTY) which goes through
# isinstance(prop, type_cls).  isinstance requires a class; _NamedStub crashes.

def test_app_ct_subsystem_property_is_class():
    import App
    from engine.appc.properties import SubsystemProperty
    assert App.CT_SUBSYSTEM_PROPERTY is SubsystemProperty


def test_app_ct_position_orientation_property_is_class():
    import App
    from engine.appc.properties import PositionOrientationProperty
    assert App.CT_POSITION_ORIENTATION_PROPERTY is PositionOrientationProperty


def test_app_ct_hull_property_is_class():
    """SDK MissionLib.py uses CT_HULL_PROPERTY in GetPropertiesByType filters."""
    import App
    from engine.appc.properties import HullProperty
    # SDK uses CT_HULL_SUBSYSTEM in the property-type slot — alias to HullProperty
    # since hardpoint sets store properties (not subsystems).
    assert App.CT_HULL_SUBSYSTEM is HullProperty


def test_loadspacehelper_create_galaxy_populates_player_impulse_max_speed():
    """The original symptom — fixed end-to-end."""
    import App
    import loadspacehelper
    App.g_kSetManager._sets.clear()
    pShip = loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)
    assert pShip is not None
    assert pShip.GetMass() == 120.0
    assert pShip.GetRotationalInertia() == 15000.0
    ies = pShip.GetImpulseEngineSubsystem()
    assert ies is not None
    assert ies.GetMaxSpeed() == 6.3
    assert ies.GetMaxAccel() == 1.5
    assert ies.GetMaxAngularVelocity() == 0.28
    assert ies.GetMaxAngularAccel() == 0.12
    hull = pShip.GetHull()
    assert hull is not None
    assert hull.GetMaxCondition() == 15000.0
