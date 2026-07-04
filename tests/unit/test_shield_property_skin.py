"""Pin the SetSkinShielding interface contract.

Originally this file pinned the TGModelProperty data-bag storage format
because SkinShielding had no explicit accessor on ShieldProperty.  After
the render-prop promotion (docs/superpowers/specs/2026-05-12-shield-render-props-design.md)
SkinShielding is a real attribute, and these tests pin the new interface:
that hardpoint scripts opting in via App.ShieldProperty_Create(...).SetSkinShielding(1)
end up with GetSkinShielding() == 1 on the property the renderer sees.
"""
from engine.appc.properties import ShieldProperty


def test_set_skin_shielding_stores_value():
    shield = ShieldProperty("Shield Generator")
    shield.SetSkinShielding(1)
    assert shield.GetSkinShielding() == 1


def test_default_skin_shielding_zero():
    shield = ShieldProperty("Shield Generator")
    assert shield.GetSkinShielding() == 0


def test_set_skin_shielding_zero_stores_zero():
    shield = ShieldProperty("Shield Generator")
    shield.SetSkinShielding(1)
    shield.SetSkinShielding(0)
    assert shield.GetSkinShielding() == 0


def _import_fresh_hardpoint(leaf):
    import sys
    import importlib
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    return importlib.import_module(f"ships.Hardpoints.{leaf}")


def test_sovereign_hardpoint_opts_into_skin_shielding():
    """Importing the SDK sovereign hardpoint yields SkinShielding=1 on its
    ShieldGenerator — set by the sovereign section of
    engine/appc/hardpoint_overrides.py via the SDK-loader hook. (This replaced
    the deleted ships/Hardpoints/sovereign.py root-shadow fork.) The module
    global and the registered template are the same object, so the override is
    visible both ways."""
    mod = _import_fresh_hardpoint("sovereign")
    assert mod.ShieldGenerator.GetSkinShielding() == 1


def test_akira_hardpoint_opts_into_skin_shielding():
    """Akira opts in purely via its hardpoint_overrides section."""
    mod = _import_fresh_hardpoint("akira")
    assert mod.ShieldGenerator.GetSkinShielding() == 1
