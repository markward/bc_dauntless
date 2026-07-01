"""TorpedoSystemProperty stores the hardpoint's ammo-slot declaration.

BC hardpoints declare ammo slots on this property: per slot
``SetMaxTorpedoes(slot, max)`` + ``SetTorpedoScript(slot, module)``, then one
``SetNumAmmoTypes(N)``.  SetupProperties later reads this back to seed one
TorpedoAmmoType per DECLARED slot (not per tube).  These setters used to land
silently in the base data-bag and were never read; these tests pin the explicit
declaration surface.
"""
from engine.appc.properties import TorpedoSystemProperty


def test_sovereign_style_declaration_round_trips():
    p = TorpedoSystemProperty("Torpedoes")
    p.SetMaxTorpedoes(0, 200)
    p.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo2")
    p.SetMaxTorpedoes(1, 60)
    p.SetTorpedoScript(1, "Tactical.Projectiles.QuantumTorpedo")
    p.SetMaxTorpedoes(2, 0)
    p.SetTorpedoScript(2, "Tactical.Projectiles.PhasedPlasma")
    p.SetNumAmmoTypes(3)

    assert p.GetNumAmmoTypes() == 3
    assert p.GetMaxTorpedoes(0) == 200
    assert p.GetMaxTorpedoes(1) == 60
    # A declared max of 0 (PhasedPlasma) is a real int 0, not None.
    assert p.GetMaxTorpedoes(2) == 0
    assert p.GetTorpedoScript(0) == "Tactical.Projectiles.PhotonTorpedo2"
    assert p.GetTorpedoScript(1) == "Tactical.Projectiles.QuantumTorpedo"


def test_undeclared_slot_max_is_none():
    """An undeclared slot returns None — the 'unlimited/undeclared' signal the
    seeding path reads to leave a fallback type without a reserve gate."""
    p = TorpedoSystemProperty("Torpedoes")
    p.SetMaxTorpedoes(0, 200)
    p.SetNumAmmoTypes(1)
    assert p.GetMaxTorpedoes(5) is None


def test_fresh_property_declares_zero_types():
    p = TorpedoSystemProperty("Torpedoes")
    assert p.GetNumAmmoTypes() == 0
