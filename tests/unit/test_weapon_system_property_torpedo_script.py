"""WeaponSystemProperty.SetTorpedoScript / GetTorpedoScript — typed per-slot
accessors. Hardpoint scripts call e.g. SetTorpedoScript(0, "Tactical.
Projectiles.PhotonTorpedo"); PR 2b's TorpedoTube.Fire reads back.
"""
from engine.appc.properties import WeaponSystemProperty


def test_get_torpedo_script_default_none():
    p = WeaponSystemProperty("Torpedoes")
    assert p.GetTorpedoScript(0) is None


def test_set_get_torpedo_script_roundtrip():
    p = WeaponSystemProperty("Torpedoes")
    p.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    assert p.GetTorpedoScript(0) == "Tactical.Projectiles.PhotonTorpedo"


def test_set_torpedo_script_multiple_slots():
    p = WeaponSystemProperty("Torpedoes")
    p.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    p.SetTorpedoScript(1, "Tactical.Projectiles.QuantumTorpedo")
    assert p.GetTorpedoScript(0) == "Tactical.Projectiles.PhotonTorpedo"
    assert p.GetTorpedoScript(1) == "Tactical.Projectiles.QuantumTorpedo"


def test_set_torpedo_script_overwrites_existing():
    p = WeaponSystemProperty("Torpedoes")
    p.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    p.SetTorpedoScript(0, "Tactical.Projectiles.QuantumTorpedo")
    assert p.GetTorpedoScript(0) == "Tactical.Projectiles.QuantumTorpedo"


def test_set_torpedo_script_coerces_slot_to_int():
    p = WeaponSystemProperty("Torpedoes")
    p.SetTorpedoScript(0.0, "Tactical.Projectiles.PhotonTorpedo")
    assert p.GetTorpedoScript(0) == "Tactical.Projectiles.PhotonTorpedo"
