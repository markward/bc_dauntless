import os
from pathlib import Path

from engine import mods, paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_suite_data_dir_is_a_temp_dir():
    layout, root = paths.data_layout()
    assert layout == "override"
    assert PROJECT_ROOT not in Path(root).resolve().parents


def test_suite_still_finds_content_without_settings_json():
    res = paths.resolve()
    assert res.ok
    assert res.source("game") in ("env", "cli")
    assert res.source("sdk") in ("env", "cli")


def test_suite_keeps_project_mods():
    if os.environ.get(mods.ENV_VAR) != str(PROJECT_ROOT / "mods"):
        return  # developer set their own DAUNTLESS_MODS_DIR
    assert mods.mods_root() == PROJECT_ROOT / "mods"
