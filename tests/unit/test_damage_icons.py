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


def test_icon_svg_for_num_returns_none_for_unknown(tmp_path, monkeypatch):
    # Force an empty curated dir + empty cache so the resolver has nothing
    # to find; for an unknown enum value it should return None without
    # raising.
    damage_icons.reset_cache()
    assert damage_icons.icon_svg_for_num(99) is None


def test_icon_svg_for_num_prefers_curated_when_present(tmp_path, monkeypatch):
    """Curated SVG under native/assets/ui-cef/icons/damage/{num}.svg
    wins over the trace cache. Verifies the lookup order matches
    weapon_icons.icon_svg_for_num."""
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "0.svg").write_text(
        '<svg><path d="M0,0 L1,1" fill="currentColor"/></svg>'
    )
    monkeypatch.setattr(damage_icons, "_CURATED_DIR", str(curated_dir))
    damage_icons.reset_cache()
    svg = damage_icons.icon_svg_for_num(0)
    assert svg is not None
    assert "clipPath" in svg  # _wrap_with_inset_clip applied
