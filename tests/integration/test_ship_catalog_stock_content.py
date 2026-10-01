"""Against the REAL configured BC content: every stock id, variant script and
icon in shipdef_overrides.py exists. Skipped when no content is configured."""
import pytest

from engine import paths
from engine.foundation import shipdef_overrides


def _stems(rel_dir, pattern):
    try:
        d = paths.sdk_scripts() / rel_dir if pattern == "*.py" else paths.game_asset(rel_dir)
    except Exception:
        pytest.skip("no BC content configured")
    if not d.is_dir():
        pytest.skip("no BC content at %s" % d)
    return {p.stem.lower() for p in d.glob(pattern)}


def test_every_stock_id_and_variant_script_is_a_real_ship_script():
    stems = _stems("ships", "*.py")
    for d in shipdef_overrides.stock_definitions():
        assert d.shipFile.lower() in stems, d.shipFile
        for v in d.dauntless.get("variants", []):
            if "script" in v:
                assert v["script"].lower() in stems, (d.shipFile, v)


def test_every_stock_icon_exists():
    icons = _stems("data/Icons/Ships", "*.tga")
    for d in shipdef_overrides.stock_definitions():
        assert d.iconName.lower() in icons, (d.shipFile, d.iconName)
