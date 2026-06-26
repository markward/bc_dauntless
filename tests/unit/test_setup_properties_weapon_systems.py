"""SetupProperties dispatches WeaponSystemProperty by WST_* to the right slot."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


def _make_ws(name, wst_type, max_c=4000.0, power=300.0, single_fire=1, aimed=0):
    p = WeaponSystemProperty(name)
    p.SetMaxCondition(max_c)
    p.SetNormalPowerPerSecond(power)
    p.SetWeaponSystemType(wst_type)
    p.SetSingleFire(single_fire)
    p.SetAimedWeapon(aimed)
    return p


def test_phaser_dispatch():
    ship = ShipClass_Create("Galaxy")
    p = _make_ws("Phasers", WeaponSystemProperty.WST_PHASER)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    phaser = ship.GetPhaserSystem()
    assert phaser.GetMaxCondition() == 4000.0
    assert phaser.GetNormalPowerPerSecond() == 300.0
    assert phaser.GetWeaponSystemType() == WeaponSystemProperty.WST_PHASER
    assert phaser.GetSingleFire() == 1


def test_torpedo_dispatch():
    ship = ShipClass_Create("Galaxy")
    p = _make_ws("Torpedoes", WeaponSystemProperty.WST_TORPEDO, max_c=2400.0, power=50.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    torp = ship.GetTorpedoSystem()
    assert torp.GetMaxCondition() == 2400.0
    assert torp.GetWeaponSystemType() == WeaponSystemProperty.WST_TORPEDO


def test_pulse_and_tractor_dispatch():
    ship = ShipClass_Create("X")
    p = _make_ws("Pulse",   WeaponSystemProperty.WST_PULSE,   power=100.0)
    t = _make_ws("Tractor", WeaponSystemProperty.WST_TRACTOR, power=75.0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.GetPropertySet().AddToSet("Scene Root", t)
    ship.SetupProperties()

    assert ship.GetPulseWeaponSystem().GetNormalPowerPerSecond() == 100.0
    assert ship.GetTractorBeamSystem().GetNormalPowerPerSecond() == 75.0
    # SingleFire from the WeaponSystemProperty must propagate to the pulse
    # system (birdofprey.py / warbird.py call SetSingleFire on the pulse
    # WeaponSystemProperty; the SetupProperties dispatch copies it through).
    assert ship.GetPulseWeaponSystem().GetSingleFire() == 1


def test_pulse_single_fire_zero_propagates():
    """SetSingleFire(0) on a pulse hardpoint (birdofprey.py DisruptorCannons)
    must land on the system as 0 — fire-all-eligible mode."""
    ship = ShipClass_Create("BoP")
    p = _make_ws("Disruptor Cannons", WeaponSystemProperty.WST_PULSE,
                 power=80.0, single_fire=0)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    assert ship.GetPulseWeaponSystem().GetSingleFire() == 0


def test_setup_properties_clears_subsystem_slots_with_no_backing_property():
    """The targets panel walks subsystem getters and treats any non-None
    return as proof the ship has that subsystem.  ShipClass_Create
    pre-allocates all eight slots so SDK callers like
    ``pShip.GetTorpedoSystem().SetAmmoType(...)`` don't null-crash, but the
    hardpoint — not the factory — must determine which subsystems a given
    ship actually has.  SetupProperties pairs every slot with its source
    template; this post-pass drops any slot the hardpoint never claimed
    (i.e. ``slot.GetProperty() is None``).

    Mirrors SDK semantics: ``escapepod.py`` registers no warp/weapons,
    ``freighter.py`` registers no phasers/torps/pulse — the populated
    subsystem set must match the populated property set.
    """
    ship = ShipClass_Create("Galaxy")
    # Only register phasers — every other slot stays property-less.
    p = _make_ws("Phasers", WeaponSystemProperty.WST_PHASER)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()

    # The one property-backed slot survives.
    assert ship.GetPhaserSystem() is not None
    # Every other pre-allocated slot was scrubbed.
    assert ship.GetTorpedoSystem() is None
    assert ship.GetPulseWeaponSystem() is None
    assert ship.GetTractorBeamSystem() is None
    assert ship.GetSensorSubsystem() is None
    assert ship.GetImpulseEngineSubsystem() is None
    assert ship.GetWarpEngineSubsystem() is None
    assert ship.GetShieldSubsystem() is None
    assert ship.GetShields() is None
    # Hull was never pre-allocated and stays None as before.
    assert ship.GetHull() is None
