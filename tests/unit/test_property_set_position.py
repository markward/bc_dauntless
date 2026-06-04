"""Bug A regression: ``SetPosition`` must be typed at the root so neither
SDK overload falls through to ``TGModelProperty.__getattr__``'s data-bag.

Before the fix every ``DorsalPhaserN.SetPosition(0, 1.27, 0.5)`` call in
``galaxy.py`` was silently stored in ``self._data`` keyed by
``("Position", (0, 1.27)) → 0.5``; ``GetPosition()`` then returned None
and ``ShipSubsystem.SetProperty`` kept the default ``(0, 0, 0)`` mount.

See ``docs/instrumented_experiments/hardpoint_handling_research.md``
section "Bug A" for the full investigation.
"""
from engine.appc.math import TGPoint3
from engine.appc.properties import (
    HullProperty,
    ObjectEmitterProperty,
    PhaserProperty,
    PositionOrientationProperty,
    SubsystemProperty,
    TGModelProperty,
)


def test_subsystem_property_three_float_form_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetPosition(0.0, 1.3, 0.16)
    got = prop.GetPosition()
    assert isinstance(got, TGPoint3)
    assert (got.x, got.y, got.z) == (0.0, 1.3, 0.16)


def test_phaser_property_three_float_form_inherited():
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetPosition(0.0, 1.27, 0.5)
    got = prop.GetPosition()
    assert (got.x, got.y, got.z) == (0.0, 1.27, 0.5)


def test_position_orientation_property_tgpoint3_form():
    prop = PositionOrientationProperty("ViewscreenForward")
    src = TGPoint3(0.0, 2.9, 0.5)
    prop.SetPosition(src)
    got = prop.GetPosition()
    assert (got.x, got.y, got.z) == (0.0, 2.9, 0.5)


def test_object_emitter_property_tgpoint3_form_round_trip():
    # Regression on the inherited setter still working for emitters.
    prop = ObjectEmitterProperty("Shuttle Bay")
    src = TGPoint3(0.0, 0.048, 0.57)
    prop.SetPosition(src)
    got = prop.GetPosition()
    assert (got.x, got.y, got.z) == (0.0, 0.048, 0.57)


def test_get_position_returns_fresh_copy():
    prop = HullProperty("Hull")
    prop.SetPosition(1.0, 2.0, 3.0)
    a = prop.GetPosition()
    a.SetXYZ(99.0, 99.0, 99.0)
    b = prop.GetPosition()
    assert (b.x, b.y, b.z) == (1.0, 2.0, 3.0)


def test_set_position_copies_source_tgpoint3():
    prop = PositionOrientationProperty("p")
    src = TGPoint3(1.0, 2.0, 3.0)
    prop.SetPosition(src)
    src.SetXYZ(77.0, 77.0, 77.0)
    got = prop.GetPosition()
    assert (got.x, got.y, got.z) == (1.0, 2.0, 3.0)


def test_get_position_returns_none_when_unset():
    prop = TGModelProperty("unset")
    assert prop.GetPosition() is None
    assert prop.GetPositionTG() is None


def test_get_position_tg_alias_returns_equivalent_point():
    prop = SubsystemProperty("warp_core")
    prop.SetPosition(0.0, -0.5, 0.0)
    a, b = prop.GetPosition(), prop.GetPositionTG()
    assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


def test_position_does_not_leak_to_data_bag():
    """The data-bag must not see a ``Position`` key after a typed call —
    that's the bug class this hoist eliminates."""
    prop = SubsystemProperty("any")
    prop.SetPosition(0.0, 1.27, 0.5)
    leaks = [k for k in prop._data.keys() if k[0] == "Position"]
    assert leaks == [], f"SetPosition fell through to data-bag: {leaks}"


def test_subsystem_property_2d_position_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetPosition2D(88.0, 20.0)
    assert prop.GetPosition2D() == (88.0, 20.0)


def test_subsystem_position_3d_and_2d_are_independent():
    prop = SubsystemProperty("Hull")
    prop.SetPosition(0.0, -1.5, -0.5)
    prop.SetPosition2D(60.0, 50.0)
    assert (prop.GetPosition().x, prop.GetPosition().y,
            prop.GetPosition().z) == (0.0, -1.5, -0.5)
    assert prop.GetPosition2D() == (60.0, 50.0)
