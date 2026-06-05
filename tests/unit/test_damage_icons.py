"""damage_icons.icon_num_for_subsystem maps a ShipSubsystem instance
to its BC ``DamageIcons`` enum value. Mapping is keyed by isinstance
checks against the engine's subsystem classes; unknown types fall
back to System (6) — the SDK's "unknown system" slot.
"""
import pytest

from engine.appc import subsystems as ss
from engine.ui import damage_icons


@pytest.mark.parametrize("cls,expected", [
    (ss.HullSubsystem,          0),
    (ss.ImpulseEngineSubsystem, 1),
    (ss.PhaserBank,             2),
    (ss.PowerSubsystem,         3),
    (ss.SensorSubsystem,        4),
    (ss.ShieldSubsystem,        5),
    (ss.TorpedoTube,            7),
    (ss.WarpEngineSubsystem,    8),
    (ss.PulseWeapon,            9),
])
def test_known_classes_map_to_expected_enum(cls, expected):
    sub = cls.__new__(cls)
    assert damage_icons.icon_num_for_subsystem(sub) == expected


def test_unknown_class_falls_back_to_system_6():
    class Bogus:
        pass
    assert damage_icons.icon_num_for_subsystem(Bogus()) == 6


def test_none_falls_back_to_system_6():
    assert damage_icons.icon_num_for_subsystem(None) == 6


def test_registry_covers_all_10_enum_values():
    """damage_icons.ICON_REGISTRY must have entries 0..9 covering the
    full DamageIcons enum, so every mapped subsystem has a traceable
    glyph available."""
    assert set(damage_icons.ICON_REGISTRY.keys()) == set(range(10))
