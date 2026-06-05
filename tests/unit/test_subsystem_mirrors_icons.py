"""ShipSubsystem.SetProperty must mirror the WeaponsDisplay icon fields
onto the runtime subsystem so the ShipDisplay snapshot can read them
without walking back to the property template.

Pattern mirrors the existing Length/Width/Position/colour-tuple mirrors
in ``engine/appc/subsystems.py:SetProperty``. icon_num=0 stays as 0 —
the panel treats 0 as the "no icon" sentinel (matches the SDK's
Destroyed-slot fallback in Icons/WeaponIcons.py:55-56), so tractor and
GenericTemplate emitters that explicitly call SetIconNum(0) propagate
the skip signal without losing fidelity.
"""
from engine.appc.properties import (
    PhaserProperty,
    SubsystemProperty,
    TorpedoTubeProperty,
    TractorBeamProperty,
)
from engine.appc.subsystems import ShipSubsystem


def test_subsystem_mirrors_icon_num_from_property():
    prop = PhaserProperty("VentralPhaser3")
    prop.SetIconNum(350)
    sub = ShipSubsystem("VentralPhaser3")
    sub.SetProperty(prop)
    assert sub.GetIconNum() == 350


def test_subsystem_mirrors_icon_position_from_property():
    prop = PhaserProperty("VentralPhaser3")
    prop.SetIconPositionX(78.0)
    prop.SetIconPositionY(42.0)
    sub = ShipSubsystem("VentralPhaser3")
    sub.SetProperty(prop)
    assert sub.GetIconPositionX() == 78.0
    assert sub.GetIconPositionY() == 42.0


def test_subsystem_mirrors_icon_above_ship_from_property():
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetIconAboveShip(1)
    sub = ShipSubsystem("DorsalPhaser1")
    sub.SetProperty(prop)
    assert sub.IsIconAboveShip() == 1

    prop2 = PhaserProperty("VentralPhaser3")
    prop2.SetIconAboveShip(0)
    sub2 = ShipSubsystem("VentralPhaser3")
    sub2.SetProperty(prop2)
    assert sub2.IsIconAboveShip() == 0


def test_subsystem_mirrors_indicator_icon_from_property():
    prop = PhaserProperty("VentralPhaser3")
    prop.SetIndicatorIconNum(506)
    prop.SetIndicatorIconPositionX(81.0)
    prop.SetIndicatorIconPositionY(45.0)
    sub = ShipSubsystem("VentralPhaser3")
    sub.SetProperty(prop)
    assert sub.GetIndicatorIconNum() == 506
    assert sub.GetIndicatorIconPositionX() == 81.0
    assert sub.GetIndicatorIconPositionY() == 45.0


def test_subsystem_mirrors_full_phaser_icon_descriptor():
    """Galaxy VentralPhaser3 sets the complete icon descriptor; the
    subsystem must surface every field by SDK-faithful accessor."""
    prop = PhaserProperty("VentralPhaser3")
    prop.SetIconNum(350)
    prop.SetIconPositionX(78.0)
    prop.SetIconPositionY(42.0)
    prop.SetIconAboveShip(0)
    prop.SetIndicatorIconNum(506)
    prop.SetIndicatorIconPositionX(81.0)
    prop.SetIndicatorIconPositionY(45.0)
    sub = ShipSubsystem("VentralPhaser3")
    sub.SetProperty(prop)
    assert (
        sub.GetIconNum(),
        sub.GetIconPositionX(),
        sub.GetIconPositionY(),
        sub.IsIconAboveShip(),
        sub.GetIndicatorIconNum(),
        sub.GetIndicatorIconPositionX(),
        sub.GetIndicatorIconPositionY(),
    ) == (350, 78.0, 42.0, 0, 506, 81.0, 45.0)


def test_subsystem_mirrors_torpedo_tube_icon():
    """Torpedo tubes have IconNum/PositionX/PositionY/AboveShip but no
    indicator; mirror still propagates the four core fields and leaves
    the indicator triplet at its zero default."""
    prop = TorpedoTubeProperty("ForwardTorpedo1")
    prop.SetIconNum(370)
    prop.SetIconPositionX(63.0)
    prop.SetIconPositionY(35.0)
    prop.SetIconAboveShip(1)
    sub = ShipSubsystem("ForwardTorpedo1")
    sub.SetProperty(prop)
    assert sub.GetIconNum() == 370
    assert sub.GetIconPositionX() == 63.0
    assert sub.GetIconPositionY() == 35.0
    assert sub.IsIconAboveShip() == 1
    assert sub.GetIndicatorIconNum() == 0


def test_subsystem_mirrors_tractor_explicit_zero_icon():
    """Tractor beams in stock BC call SetIconNum(0) / SetIndicatorIconNum(0)
    explicitly — the "no icon" sentinel. Mirror preserves 0 so the panel
    can skip those mounts."""
    prop = TractorBeamProperty("ForwardTractor")
    prop.SetIconNum(0)
    prop.SetIndicatorIconNum(0)
    sub = ShipSubsystem("ForwardTractor")
    sub.SetProperty(prop)
    assert sub.GetIconNum() == 0
    assert sub.GetIndicatorIconNum() == 0


def test_subsystem_icon_defaults_zero_when_property_unset():
    """A SubsystemProperty that was never configured leaves the subsystem
    at the zero defaults so the panel skips drawing."""
    prop = SubsystemProperty("unset")
    sub = ShipSubsystem("unset")
    sub.SetProperty(prop)
    assert sub.GetIconNum() == 0
    assert sub.GetIndicatorIconNum() == 0
    assert sub.IsIconAboveShip() == 0


def test_subsystem_icon_fields_default_zero_without_property():
    """Bare ShipSubsystem with no property bound exposes the zero
    defaults so callers don't need to None-check before reading."""
    sub = ShipSubsystem("bare")
    assert sub.GetIconNum() == 0
    assert sub.GetIconPositionX() == 0.0
    assert sub.GetIconPositionY() == 0.0
    assert sub.IsIconAboveShip() == 0
    assert sub.GetIndicatorIconNum() == 0
    assert sub.GetIndicatorIconPositionX() == 0.0
    assert sub.GetIndicatorIconPositionY() == 0.0


def test_subsystem_mirrors_position_2d_from_property():
    """SubsystemProperty.SetPosition2D values must round-trip onto the
    runtime ShipSubsystem so the ship-display panel can read x/y_px
    without re-walking the property tree. Matches the existing
    IconNum / IconPosition mirror pattern."""
    from engine.appc import properties as p, subsystems as s
    prop = p.HullProperty("Hull")
    prop.SetPosition2D(64.0, 40.0)
    sub = s.HullSubsystem("Hull")
    sub.SetProperty(prop)
    assert sub.GetPosition2D() == (64.0, 40.0)


def test_subsystem_position_2d_defaults_to_origin():
    """Subsystems without a Position2D set must report (0.0, 0.0).
    The damage descriptor builder treats (0,0) as "hide from panel" so
    Phase 1 ships without hardpoint coords stay invisible by default."""
    from engine.appc import properties as p, subsystems as s
    prop = p.HullProperty("Hull")
    sub = s.HullSubsystem("Hull")
    sub.SetProperty(prop)
    assert sub.GetPosition2D() == (0.0, 0.0)
