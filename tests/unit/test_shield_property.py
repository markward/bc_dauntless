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
