"""ShieldProperty: real per-face accessors (not data-bag shims)."""
from engine.appc.properties import ShieldProperty


def test_max_shields_defaults_zero():
    p = ShieldProperty("Shield Generator")
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert p.GetMaxShields(face) == 0.0


def test_max_shields_round_trip_per_face():
    p = ShieldProperty("Shield Generator")
    p.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    p.SetMaxShields(ShieldProperty.REAR_SHIELDS,  4000.0)
    assert p.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert p.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    assert p.GetMaxShields(ShieldProperty.TOP_SHIELDS) == 0.0


def test_charge_per_second_round_trip_per_face():
    p = ShieldProperty("Shield Generator")
    p.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    p.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS,  20.0)
    assert p.GetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS) == 10.0
    assert p.GetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS) == 20.0
    assert p.GetShieldChargePerSecond(ShieldProperty.TOP_SHIELDS) == 0.0


def test_methods_are_real_not_databag_shim():
    """The methods must exist on the class itself, not be synthesized by
    TGModelProperty.__getattr__.  Without this, the SDK call sites would
    keep round-tripping through the data-bag and the accessors would
    return None for unset faces (vs. 0.0)."""
    assert "GetMaxShields" in vars(ShieldProperty)
    assert "SetMaxShields" in vars(ShieldProperty)
    assert "GetShieldChargePerSecond" in vars(ShieldProperty)
    assert "SetShieldChargePerSecond" in vars(ShieldProperty)
    # A real bound method has __self__; a __getattr__-synthesized closure
    # is a plain function without it.
    p = ShieldProperty("X")
    assert p.GetMaxShields.__self__ is p


import App


def test_skin_shielding_default_zero():
    p = ShieldProperty("Shield Generator")
    assert p.GetSkinShielding() == 0


def test_skin_shielding_round_trip():
    p = ShieldProperty("Shield Generator")
    p.SetSkinShielding(1)
    assert p.GetSkinShielding() == 1
    p.SetSkinShielding(0)
    assert p.GetSkinShielding() == 0


def test_skin_shielding_coerces_to_int():
    p = ShieldProperty("Shield Generator")
    p.SetSkinShielding("1")
    assert p.GetSkinShielding() == 1


def test_shield_glow_decay_default_one():
    p = ShieldProperty("Shield Generator")
    assert p.GetShieldGlowDecay() == 1.0


def test_shield_glow_decay_round_trip():
    p = ShieldProperty("Shield Generator")
    p.SetShieldGlowDecay(2.5)
    assert p.GetShieldGlowDecay() == 2.5


def test_shield_glow_decay_coerces_to_float():
    p = ShieldProperty("Shield Generator")
    p.SetShieldGlowDecay("2.5")
    assert p.GetShieldGlowDecay() == 2.5


def test_shield_glow_color_default_none():
    """None is the 'absent' marker; engine/shields.py treats it as white."""
    p = ShieldProperty("Shield Generator")
    assert p.GetShieldGlowColor() is None


def test_shield_glow_color_round_trip():
    p = ShieldProperty("Shield Generator")
    color = App.TGColorA()
    color.SetRGBA(0.2, 0.4, 0.8, 1.0)
    p.SetShieldGlowColor(color)
    got = p.GetShieldGlowColor()
    assert got is color


def test_new_render_prop_methods_are_real_not_databag_shim():
    """Each new method must live on the class itself, not be synthesized
    by TGModelProperty.__getattr__."""
    for name in (
        "GetSkinShielding", "SetSkinShielding",
        "GetShieldGlowDecay", "SetShieldGlowDecay",
        "GetShieldGlowColor", "SetShieldGlowColor",
    ):
        assert name in vars(ShieldProperty), f"{name} missing from class"
    p = ShieldProperty("X")
    assert p.GetSkinShielding.__self__ is p
    assert p.SetShieldGlowColor.__self__ is p


def test_set_shield_glow_color_records_to_tracker():
    """Tracker hook must survive the promotion from __getattr__ shim
    to real method. Recorded name must match the pre-refactor shim's
    behavior."""
    App._color_consumer_tracker.clear()
    App._color_consumer_tracker.enable()
    App._stub_tracker.clear()
    App._stub_tracker.set_mission("tracker_test")

    try:
        p = ShieldProperty("Shield Generator")
        color = App.TGColorA()
        color.SetRGBA(0.5, 0.5, 0.5, 1.0)
        p.SetShieldGlowColor(color)
    finally:
        App._color_consumer_tracker.disable()
        App._stub_tracker.reset_mission()

    rows = App._color_consumer_tracker.report()
    names = [r[0] for r in rows]
    assert "ShieldProperty.SetShieldGlowColor" in names
