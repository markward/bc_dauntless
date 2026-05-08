import pytest
from engine.appc.properties import TGModelProperty


def test_name_storage():
    p = TGModelProperty("Hull")
    assert p.GetName() == "Hull"
    p.SetName("New Hull")
    assert p.GetName() == "New Hull"


def test_bool_is_true():
    p = TGModelProperty("X")
    assert bool(p) is True


def test_repr_contains_class_and_name():
    p = TGModelProperty("Hull")
    assert "TGModelProperty" in repr(p)
    assert "Hull" in repr(p)


def test_data_bag_single_arg():
    p = TGModelProperty("X")
    p.SetMaxCondition(5000)
    assert p.GetMaxCondition() == 5000


def test_data_bag_multi_arg():
    p = TGModelProperty("X")
    p.SetMaxShields(0, 4500.0)
    p.SetMaxShields(1, 3000.0)
    assert p.GetMaxShields(0) == 4500.0
    assert p.GetMaxShields(1) == 3000.0


def test_data_bag_unknown_returns_none():
    p = TGModelProperty("X")
    assert p.GetMaxCondition() is None
    assert p.GetMaxShields(0) is None


def test_unknown_attribute_raises():
    p = TGModelProperty("X")
    with pytest.raises(AttributeError):
        p.NotASetterOrGetter


from engine.appc.properties import (
    PositionOrientationProperty, EngineGlowProperty,
    SubsystemProperty, HullProperty, PowerProperty,
    WeaponProperty, EnergyWeaponProperty,
    PhaserProperty, PulseWeaponProperty, TractorBeamProperty,
    TorpedoTubeProperty,
    PoweredSubsystemProperty,
    ShieldProperty, SensorProperty, RepairSubsystemProperty,
    WeaponSystemProperty, TorpedoSystemProperty,
)


def test_subclass_isinstance_chain():
    p = PhaserProperty("X")
    assert isinstance(p, EnergyWeaponProperty)
    assert isinstance(p, WeaponProperty)
    assert isinstance(p, SubsystemProperty)
    assert isinstance(p, TGModelProperty)


def test_shield_property_inherits_powered_subsystem():
    p = ShieldProperty("X")
    assert isinstance(p, PoweredSubsystemProperty)
    assert isinstance(p, SubsystemProperty)


def test_torpedo_system_inherits_weapon_system():
    p = TorpedoSystemProperty("X")
    assert isinstance(p, WeaponSystemProperty)
    assert isinstance(p, PoweredSubsystemProperty)


def test_shield_face_constants():
    assert ShieldProperty.FRONT_SHIELDS == 0
    assert ShieldProperty.REAR_SHIELDS == 1
    assert ShieldProperty.TOP_SHIELDS == 2
    assert ShieldProperty.BOTTOM_SHIELDS == 3
    assert ShieldProperty.LEFT_SHIELDS == 4
    assert ShieldProperty.RIGHT_SHIELDS == 5
    assert ShieldProperty.NUM_SHIELDS == 6


def test_weapon_system_type_constants():
    assert WeaponSystemProperty.WST_UNKNOWN == 0
    assert WeaponSystemProperty.WST_PHASER == 1
    assert WeaponSystemProperty.WST_TORPEDO == 2
    assert WeaponSystemProperty.WST_PULSE == 3
    assert WeaponSystemProperty.WST_TRACTOR == 4


def test_data_bag_works_on_subclasses():
    p = ShieldProperty("Shield Generator")
    p.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 4500.0)
    assert p.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 4500.0
