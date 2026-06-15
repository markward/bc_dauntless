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


def test_sovereign_hardpoint_opts_into_skin_shielding():
    """Importing the project-root sovereign hardpoint should result in
    SkinShielding=1 on its ShieldGenerator. Indirectly verifies that
    ships/Hardpoints/sovereign.py shadows the SDK copy via _SDKFinder."""
    import sys
    import importlib
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]
    mod = importlib.import_module("ships.Hardpoints.sovereign")
    sg = getattr(mod, "ShieldGenerator")
    assert sg.GetSkinShielding() == 1
