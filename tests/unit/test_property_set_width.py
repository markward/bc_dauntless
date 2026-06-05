"""Bug C regression: ``EnergyWeaponProperty.SetWidth`` must be typed.

Galaxy hardpoints call ``DorsalPhaser1.SetWidth(1.35)`` to set the
phaser-strip's lateral dimension perpendicular to ``Length``.  Distinct
from ``PhaserProperty.SetPhaserWidth`` (the beam thickness) -- different
SDK methods, different fields.

Before this fix ``SetWidth`` fell through ``TGModelProperty.__getattr__``
to the data-bag and was silently dropped, so ``GetWidth()`` always
returned None.  The deferred TODO in
``docs/superpowers/deferred/2026-05-18-phaser-hardpoint-coverage.md``
had noted this without realising it was being eaten by the data-bag.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug C" for the full investigation.
"""
from engine.appc.properties import (
    EnergyWeaponProperty,
    PhaserProperty,
    PulseWeaponProperty,
    TractorBeamProperty,
)


def test_set_width_round_trip():
    p = PhaserProperty("DorsalPhaser1")
    p.SetWidth(1.35)
    assert p.GetWidth() == 1.35


def test_set_width_default_zero():
    p = PhaserProperty("any")
    assert p.GetWidth() == 0.0


def test_set_width_available_across_energy_weapon_hierarchy():
    for cls in (EnergyWeaponProperty, PhaserProperty,
                PulseWeaponProperty, TractorBeamProperty):
        p = cls("any")
        p.SetWidth(0.42)
        assert p.GetWidth() == 0.42


def test_set_width_does_not_leak_to_data_bag():
    p = PhaserProperty("DorsalPhaser1")
    p.SetWidth(1.35)
    leaks = [k for k in p._data.keys() if k[0] == "Width"]
    assert leaks == [], f"SetWidth fell through to data-bag: {leaks}"


def test_width_distinct_from_phaser_width():
    """PhaserWidth is the beam thickness (PhaserProperty-only); Width is
    the strip's lateral dimension (EnergyWeaponProperty).  They share
    no storage."""
    p = PhaserProperty("DorsalPhaser1")
    p.SetWidth(1.35)
    p.SetPhaserWidth(0.30)
    assert p.GetWidth() == 1.35
    assert p.GetPhaserWidth() == 0.30
