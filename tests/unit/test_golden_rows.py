"""The golden row vocabulary (tests/helpers/golden_rows.py): light, no engine."""
import subprocess
from pathlib import Path
import sys

from tests.helpers import golden_rows
from tests.helpers.golden_rows import (describe, differences, first_difference,
                                       row_difference)


def test_first_difference_names_path():
    assert first_difference([0, [1, 2]], [0, [1, 3]]) == ((1, 1), 2, 3)


def test_differences_lists_all_up_to_limit():
    assert len(differences([1, 2, 3], [4, 5, 6], limit=2)) == 2
    assert len(differences([1, 2, 3], [4, 5, 6], limit=10)) == 3


def test_describe_names_kind_label_field():
    row = ["weapon", "Player/Phaser 1", ["bool", True], "Enemy-1",
           ["float", "0x1p+0"]]
    text = describe(2, (1, 0, 4), (2, [row], [], [], [], [], []))
    assert "tick 2" in text
    assert "weapon 'Player/Phaser 1'" in text
    assert "_fire_timer" in text


def test_row_difference_names_field_for_tuple_rows():
    def tick(timer):
        row = ["weapon", "Player/Phaser 1", ["bool", True], "Enemy-1",
               ["float", timer]]
        return (2, [row], [], [], [], [], [])

    assert row_difference(2, tick("0x1p+0"), tick("0x1p+0")) is None
    msg = row_difference(2, tick("0x1p+0"), tick("0x1p+1"))
    assert "tick 2" in msg
    assert "weapon 'Player/Phaser 1'" in msg
    assert "_fire_timer" in msg
    assert "0x1p+0" in msg and "0x1p+1" in msg


def test_module_is_light():
    code = ("import tests.helpers.golden_rows, sys; "
            "assert 'engine' not in sys.modules "
            "and 'App' not in sys.modules "
            "and 'pytest' not in sys.modules")
    root = Path(__file__).resolve().parents[2]
    assert subprocess.run([sys.executable, "-c", code],
                          cwd=root).returncode == 0


def test_no_recordings_are_committed():
    """The recordings are retired: scenes are code, compared across commits
    by the A/B tool, never stored."""
    assert not (Path(__file__).resolve().parents[1] / "fixtures"
                / "golden_fights").exists()


def test_subsystems_scene_is_a_golden_scene():
    from tests.helpers import golden_fight
    scene = golden_fight.SCENES["native_subsystems_scene"]
    assert scene.ticks == 600
    assert scene.run is golden_fight._native_subsystems
    assert golden_rows.COMPONENTS is golden_fight.COMPONENTS
