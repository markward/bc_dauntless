"""Bug regression: WeaponsDisplay-icon setters must be typed at
``SubsystemProperty`` so they stop falling through
``TGModelProperty.__getattr__``'s data-bag.

Before the fix every ``DorsalPhaserN.SetIconNum(330)`` /
``SetIconPositionX(78)`` / ``SetIconAboveShip(1)`` /
``SetIndicatorIconNum(506)`` call in stock hardpoints was silently
stored in ``self._data`` keyed by ``(field, ()) → value``. The
data-bag round-trips for single-arg setters happen to recover the
value, but the typed setters lock the contract in so future authors
can't accidentally regress (Bug C / D / F class).

See ``docs/instrumented_experiments/weapons_panel_icons_prompt.md``
for the full investigation that motivates this hoist.
"""
from engine.appc.properties import (
    EnergyWeaponProperty,
    PhaserProperty,
    SubsystemProperty,
    TorpedoTubeProperty,
    TractorBeamProperty,
)


def test_subsystem_property_set_icon_num_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIconNum(350)
    assert prop.GetIconNum() == 350


def test_subsystem_property_set_icon_position_x_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIconPositionX(78.0)
    assert prop.GetIconPositionX() == 78.0


def test_subsystem_property_set_icon_position_y_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIconPositionY(42.0)
    assert prop.GetIconPositionY() == 42.0


def test_subsystem_property_set_icon_above_ship_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIconAboveShip(0)
    # SDK exposes IsIconAboveShip() returning 0/1.
    assert prop.IsIconAboveShip() == 0
    prop.SetIconAboveShip(1)
    assert prop.IsIconAboveShip() == 1


def test_subsystem_property_set_indicator_icon_num_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIndicatorIconNum(506)
    assert prop.GetIndicatorIconNum() == 506


def test_subsystem_property_set_indicator_icon_position_x_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIndicatorIconPositionX(81.0)
    assert prop.GetIndicatorIconPositionX() == 81.0


def test_subsystem_property_set_indicator_icon_position_y_round_trip():
    prop = SubsystemProperty("VentralPhaser3")
    prop.SetIndicatorIconPositionY(45.0)
    assert prop.GetIndicatorIconPositionY() == 45.0


def test_icon_setters_inherited_by_phaser_property():
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetIconNum(340)
    prop.SetIconPositionX(12.0)
    prop.SetIconPositionY(40.0)
    prop.SetIconAboveShip(1)
    prop.SetIndicatorIconNum(500)
    prop.SetIndicatorIconPositionX(15.0)
    prop.SetIndicatorIconPositionY(43.0)
    assert prop.GetIconNum() == 340
    assert prop.GetIconPositionX() == 12.0
    assert prop.GetIconPositionY() == 40.0
    assert prop.IsIconAboveShip() == 1
    assert prop.GetIndicatorIconNum() == 500
    assert prop.GetIndicatorIconPositionX() == 15.0
    assert prop.GetIndicatorIconPositionY() == 43.0


def test_icon_setters_inherited_by_torpedo_tube_property():
    prop = TorpedoTubeProperty("ForwardTorpedo1")
    prop.SetIconNum(370)
    prop.SetIconPositionX(63.0)
    prop.SetIconPositionY(35.0)
    prop.SetIconAboveShip(1)
    assert prop.GetIconNum() == 370
    assert prop.GetIconPositionX() == 63.0
    assert prop.GetIconPositionY() == 35.0
    assert prop.IsIconAboveShip() == 1


def test_icon_setters_inherited_by_tractor_beam_property():
    prop = TractorBeamProperty("ForwardTractor")
    prop.SetIconNum(0)
    prop.SetIndicatorIconNum(0)
    assert prop.GetIconNum() == 0
    assert prop.GetIndicatorIconNum() == 0


def test_icon_defaults_are_zero_or_none():
    """An emitter that never set its icon fields exposes sentinel defaults
    so the panel can skip emitting a descriptor instead of drawing
    a stray icon at (0, 0). IconNum=0 = "no icon" matches the SDK's
    Destroyed-slot fallback in WeaponIcons.py:55."""
    prop = SubsystemProperty("unset")
    assert prop.GetIconNum() == 0
    assert prop.GetIconPositionX() == 0.0
    assert prop.GetIconPositionY() == 0.0
    assert prop.IsIconAboveShip() == 0
    assert prop.GetIndicatorIconNum() == 0
    assert prop.GetIndicatorIconPositionX() == 0.0
    assert prop.GetIndicatorIconPositionY() == 0.0


def test_icon_setters_do_not_leak_to_data_bag():
    """The data-bag must not see Icon* keys after typed calls — that's
    the bug class this hoist eliminates."""
    prop = PhaserProperty("DorsalPhaser1")
    prop.SetIconNum(340)
    prop.SetIconPositionX(12.0)
    prop.SetIconPositionY(40.0)
    prop.SetIconAboveShip(1)
    prop.SetIndicatorIconNum(500)
    prop.SetIndicatorIconPositionX(15.0)
    prop.SetIndicatorIconPositionY(43.0)
    leaks = sorted(k for k in prop._data.keys()
                   if k[0].startswith("Icon")
                   or k[0].startswith("IndicatorIcon"))
    assert leaks == [], f"icon setters fell through to data-bag: {leaks}"


def test_energy_weapon_property_indicator_round_trip():
    """Make sure the bonus EnergyWeaponProperty inheritance is preserved
    even though indicator setters are declared on the base."""
    prop = EnergyWeaponProperty("VentralPhaser3")
    prop.SetIndicatorIconNum(506)
    prop.SetIndicatorIconPositionX(81.0)
    prop.SetIndicatorIconPositionY(45.0)
    assert prop.GetIndicatorIconNum() == 506
    assert prop.GetIndicatorIconPositionX() == 81.0
    assert prop.GetIndicatorIconPositionY() == 45.0
