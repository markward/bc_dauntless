"""End-to-end torpedo ammo-type flow, mirroring the real SDK runtime with ZERO
UI-side filtering.

The engine only provides the surface; the SDK scripts curate the list:
- SetupProperties seeds one ammo type per hardpoint-declared slot (named by the
  projectile module's GetName()).
- QuickBattle.py:2917-2924 prunes every slot past index 1 (RemoveAmmoType),
  dropping PhasedPlasma so a Sovereign lists only Photon + Quantum.
- Missions (E3M1.py) save/restore round counts via GetNumAvailableTorpsToType /
  LoadAmmoType.

read_weapon_config then reports exactly the curated types with no string surgery.
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    TorpedoTubeProperty, WeaponSystemProperty, TorpedoSystemProperty,
)
from engine.appc import weapon_config


def _sovereign_like_ship():
    """A ship with the Sovereign hardpoint's 3-slot torpedo declaration plus
    tubes (sovereign.py:609-633)."""
    ship = ShipClass_Create("Sovereign")
    for i in range(4):
        tube = TorpedoTubeProperty(f"Torpedo {i}")
        tube.SetMaxCondition(2400.0)
        ship.GetPropertySet().AddToSet("Scene Root", tube)
    prop = TorpedoSystemProperty("Torpedoes")
    prop.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    prop.SetMaxTorpedoes(0, 200)
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo2")
    prop.SetMaxTorpedoes(1, 60)
    prop.SetTorpedoScript(1, "Tactical.Projectiles.QuantumTorpedo")
    prop.SetMaxTorpedoes(2, 0)
    prop.SetTorpedoScript(2, "Tactical.Projectiles.PhasedPlasma")
    prop.SetNumAmmoTypes(3)
    ship.GetPropertySet().AddToSet("Scene Root", prop)
    ship.SetupProperties()
    return ship


def _quickbattle_prune(torps):
    """QuickBattle.py:2917-2924 verbatim — drop every ammo type past index 1."""
    iNumTypes = torps.GetNumAmmoTypes()
    for iType in range(iNumTypes):
        if iType >= 2:
            torps.RemoveAmmoType(iType)


def test_setup_seeds_declared_types_named_by_getname():
    ts = _sovereign_like_ship().GetTorpedoSystem()
    assert ts.GetNumAmmoTypes() == 3
    assert [ts.GetAmmoType(i).GetAmmoName() for i in range(3)] == [
        "Photon", "Quantum", "Phased"]


def test_quickbattle_prune_leaves_photon_and_quantum():
    ship = _sovereign_like_ship()
    ts = ship.GetTorpedoSystem()

    _quickbattle_prune(ts)

    # PhasedPlasma is gone; the Type selector shows exactly Photon + Quantum.
    assert ts.GetNumAmmoTypes() == 2
    assert [ts.GetAmmoType(i).GetAmmoName() for i in range(2)] == ["Photon", "Quantum"]

    cfg = weapon_config.read_weapon_config(ship)
    assert cfg["torp_types"] == ["Photon", "Quantum"]
    assert cfg["torp_types_cyclable"] is True
    assert "Phased" not in cfg["torp_types"]
    assert "PhotonTorpedo2" not in cfg["torp_types"]  # the leaf-leak bug


def test_e3m1_style_save_load_round_trip():
    """E3M1 SaveTorpCount/RestoreTorpCount: read counts, expend some, re-load the
    difference.  The reserve must track and nothing may raise."""
    ship = _sovereign_like_ship()
    ts = ship.GetTorpedoSystem()
    _quickbattle_prune(ts)

    # SaveTorpCount — snapshot the full loadout (seeded to declared max).
    initial = [ts.GetNumAvailableTorpsToType(0), ts.GetNumAvailableTorpsToType(1)]
    assert initial == [200, 60]

    # Expend some (mission gameplay would fire these).
    ts.LoadAmmoType(0, -30)
    ts.LoadAmmoType(1, -10)
    assert ts.GetNumAvailableTorpsToType(0) == 170
    assert ts.GetNumAvailableTorpsToType(1) == 50

    # RestoreTorpCount — reload the difference back to the initial snapshot.
    ts.LoadAmmoType(0, initial[0] - ts.GetNumAvailableTorpsToType(0))
    ts.LoadAmmoType(1, initial[1] - ts.GetNumAvailableTorpsToType(1))
    assert ts.GetNumAvailableTorpsToType(0) == 200
    assert ts.GetNumAvailableTorpsToType(1) == 60
