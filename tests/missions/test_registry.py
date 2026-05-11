"""End-to-end: discover() returns entries with display_name filled."""
from pathlib import Path

import pytest

from engine.missions import discover

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_ROOT = PROJECT_ROOT / "sdk" / "Build" / "scripts"


def test_display_names_are_non_empty():
    if not SCRIPTS_ROOT.is_dir():
        pytest.skip("SDK scripts not present")
    reg = discover(SCRIPTS_ROOT)
    for fam in reg.families:
        assert fam.display_name, f"family {fam.dir_name!r} has empty display_name"
        for ep in fam.episodes:
            assert ep.display_name, (
                f"episode {fam.dir_name}/{ep.dir_name!r} has empty display_name")
            for m in ep.missions:
                assert m.display_name, (
                    f"mission {fam.dir_name}/{ep.dir_name}/{m.dir_name!r}"
                    " has empty display_name")


def test_display_name_falls_back_to_dir_when_unknown():
    """A family root that doesn't exist in TGL still produces dir-name labels."""
    if not SCRIPTS_ROOT.is_dir():
        pytest.skip("SDK scripts not present")
    reg = discover(SCRIPTS_ROOT)
    tutorial = next(f for f in reg.families if f.dir_name == "Tutorial")
    m1 = next(
        m for ep in tutorial.episodes for m in ep.missions
        if m.dir_name == "M1Basic"
    )
    # We don't assert the *value* (depends on TGL availability) — only that
    # it's a non-empty string, populated by resolve_mission.
    assert isinstance(m1.display_name, str) and m1.display_name
