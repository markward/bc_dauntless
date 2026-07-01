"""SetupProperties Pass 2: seed one TorpedoAmmoType per DECLARED ammo slot.

BC declares a ship's selectable torpedo ammo as SLOTS on the
TorpedoSystemProperty (per slot SetTorpedoScript + SetMaxTorpedoes, then
SetNumAmmoTypes(N)) — NOT one type per tube.  Each type is named by its
projectile module's GetName() (Photon/Quantum/Phased), not the class leaf.
"""
from engine.appc.ships import ShipClass_Create, _resolve_torpedo_ammo
from engine.appc.properties import (
    TorpedoTubeProperty, WeaponSystemProperty, TorpedoSystemProperty,
)


def _make_tube(name):
    p = TorpedoTubeProperty(name)
    p.SetMaxCondition(2400.0)
    return p


def _torpedo_system_property(slots):
    """A TorpedoSystemProperty like a real hardpoint registers (WST_TORPEDO so
    the Pass 3 scrub keeps the subsystem).  ``slots`` is a list of (script, max)
    declared per slot; SetNumAmmoTypes is stamped to len(slots)."""
    prop = TorpedoSystemProperty("Torpedoes")
    prop.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    for i, (script, mx) in enumerate(slots):
        if script is not None:
            prop.SetTorpedoScript(i, script)
        if mx is not None:
            prop.SetMaxTorpedoes(i, mx)
    prop.SetNumAmmoTypes(len(slots))
    return prop


def test_ammo_types_decoupled_from_tube_count():
    """Six tubes but the hardpoint declares ONE ammo type → one ammo type.
    Tubes are launchers; ammo TYPES are a separate per-slot declaration."""
    ship = ShipClass_Create("Galaxy")
    for i in range(6):
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))
    ship.GetPropertySet().AddToSet(
        "Scene Root",
        _torpedo_system_property([("Tactical.Projectiles.PhotonTorpedo", 250)]),
    )
    ship.SetupProperties()

    ts = ship.GetTorpedoSystem()
    assert ts.GetNumAmmoTypes() == 1
    assert ts.GetAmmoType(0).GetAmmoName() == "Photon"
    assert ts.GetAmmoType(0).GetMaxTorpedoes() == 250
    assert ts.GetAmmoType(0).GetLaunchSpeed() > 0.0


def test_sovereign_style_three_slots_named_by_getname():
    """Sovereign declares PhotonTorpedo2 / QuantumTorpedo / PhasedPlasma.  The
    seeded names come from each module's GetName() (Photon/Quantum/Phased), NOT
    the leaf — the fix for 'PhotonTorpedo2' and 'PhasedPlasma' leaking into the
    Type selector."""
    ship = ShipClass_Create("Sovereign")
    for i in range(4):  # 4 tubes, but 3 declared ammo types
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))
    ship.GetPropertySet().AddToSet("Scene Root", _torpedo_system_property([
        ("Tactical.Projectiles.PhotonTorpedo2", 200),
        ("Tactical.Projectiles.QuantumTorpedo", 60),
        ("Tactical.Projectiles.PhasedPlasma", 0),
    ]))
    ship.SetupProperties()

    ts = ship.GetTorpedoSystem()
    assert ts.GetNumAmmoTypes() == 3
    assert [ts.GetAmmoType(i).GetAmmoName() for i in range(3)] == [
        "Photon", "Quantum", "Phased"]
    assert [ts.GetAmmoType(i).GetMaxTorpedoes() for i in range(3)] == [200, 60, 0]


def test_no_tubes_no_seeding():
    """A ship whose hardpoint registers no TorpedoTubeProperty and no
    WeaponSystemProperty(WST_TORPEDO) has no torpedo subsystem at all."""
    ship = ShipClass_Create("FedStarbase")
    ship.SetupProperties()
    assert ship.GetTorpedoSystem() is None


def test_undeclared_hull_falls_back_to_single_photon():
    """A hull with tubes but no SetNumAmmoTypes (a plain WeaponSystemProperty)
    still gets one unlimited Photon type so firing works (launch speed > 0)."""
    ship = ShipClass_Create("Galaxy")
    for i in range(3):
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))
    sys_prop = WeaponSystemProperty("Torpedoes")  # NOT a TorpedoSystemProperty
    sys_prop.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    ship.GetPropertySet().AddToSet("Scene Root", sys_prop)
    ship.SetupProperties()

    ts = ship.GetTorpedoSystem()
    assert ts.GetNumAmmoTypes() == 1
    assert ts.GetAmmoType(0).GetAmmoName() == "Photon"
    assert ts.GetAmmoType(0).GetLaunchSpeed() > 0.0


# ── _resolve_torpedo_ammo unit behaviour ──────────────────────────────────────

def test_resolve_names_by_getname_photon2():
    """PhotonTorpedo2.GetName() == "Photon" — the leaf "PhotonTorpedo2" must NOT
    survive (regression guard for the leaf-strip heuristic)."""
    ts_prop = TorpedoSystemProperty("Torpedoes")
    ts_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo2")
    ts_prop.SetMaxTorpedoes(0, 200)
    ammo = _resolve_torpedo_ammo(ts_prop, 0)
    assert ammo.GetAmmoName() == "Photon"
    assert ammo.GetMaxTorpedoes() == 200


def test_resolve_names_phased_plasma():
    """PhasedPlasma.GetName() == "Phased" — not "PhasedPlasma"."""
    ts_prop = TorpedoSystemProperty("Torpedoes")
    ts_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhasedPlasma")
    ts_prop.SetMaxTorpedoes(0, 0)
    ammo = _resolve_torpedo_ammo(ts_prop, 0)
    assert ammo.GetAmmoName() == "Phased"


def test_photon_torpedo_ammo_stamps_power_cost():
    """Each seeded TorpedoAmmoType carries the projectile script's GetPowerCost()
    (PhotonTorpedo.py:65 → 20.0) for the per-shot power debit."""
    ts_prop = TorpedoSystemProperty("Torpedoes")
    ts_prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    ammo = _resolve_torpedo_ammo(ts_prop, 0)
    assert ammo.GetPowerCost() == 20.0
    assert ammo.GetAmmoName() == "Photon"


def test_unresolved_script_defaults_to_photon():
    """Resolver fallback (no script for the slot) yields Photon with the Photon
    power cost and an unlimited reserve."""
    ts_prop = TorpedoSystemProperty("Torpedoes")
    ammo = _resolve_torpedo_ammo(ts_prop, 0)
    assert ammo.GetAmmoName() == "Photon"
    assert ammo.GetPowerCost() == 20.0


def test_idempotent_against_re_run():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", _torpedo_system_property([
        ("Tactical.Projectiles.PhotonTorpedo", 250),
        ("Tactical.Projectiles.QuantumTorpedo", 60),
    ]))
    for i in range(2):
        ship.GetPropertySet().AddToSet("Scene Root", _make_tube(f"Torpedo {i}"))

    ship.SetupProperties()
    assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 2
    # Re-run: should not double-seed.
    ship.SetupProperties()
    assert ship.GetTorpedoSystem().GetNumAmmoTypes() == 2
