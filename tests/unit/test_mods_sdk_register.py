from pathlib import Path

from engine import mods


def setup_function():
    mods.configure(None)


def teardown_function():
    mods.configure(None)


def test_register_sdk_file_adds_an_sdk_entry(tmp_path):
    p = tmp_path / "zz.py"
    p.write_text("#")
    mods.register_sdk_file("Custom/Ships/zz_Dauntless_X.py", p, "M")
    mf = mods.current().lookup("custom/ships/zz_dauntless_x.py")
    assert mf is not None and mf.target == "sdk" and mf.mod_name == "M"  # paths-guard: kind label
    assert mf.abs_path == Path(p) and mf.raw_rel == "Custom/Ships/zz_Dauntless_X.py"
    assert mods.sdk_override("Custom/Ships/zz_Dauntless_X.py") == Path(p)


def test_mods_screen_requested():
    assert mods.mods_screen_requested(["--mods"]) is True
    assert mods.mods_screen_requested(["--developer"]) is False
    assert mods.MODS_SCREEN_FLAG == "--mods"
