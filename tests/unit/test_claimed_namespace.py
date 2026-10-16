"""Custom.NanoFXv2 is Dauntless's, always (spec 2026-10-16 §8.1)."""
import importlib
import sys

import pytest

from engine import mods
from engine.compat import claimed


@pytest.fixture(autouse=True)
def _clean():
    mods.configure(None)
    claimed.reset()
    yield
    for name in [n for n in sys.modules if n.lower().startswith("custom.nanofxv2")]:
        sys.modules.pop(name, None)
    mods.configure(None)
    claimed.reset()


def _touch(p, body="x = 1\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_package_and_config_come_from_dauntless():
    pkg = importlib.import_module("Custom.NanoFXv2")
    cfg = importlib.import_module("Custom.NanoFXv2.NanoFX_Config")
    assert "engine/compat/fx_api" in pkg.__file__.replace("\\", "/")
    assert cfg.sFX_Enabled == 1 and cfg.eFX_LightFlickerFX == "On"


def test_ours_beats_a_mod_copy(tmp_path):
    _touch(tmp_path / "M" / "scripts" / "Custom" / "NanoFXv2" / "NanoFX_Config.py",
           "sFX_Enabled = 0\n")
    mods.configure(mods.build_index(tmp_path))
    cfg = importlib.import_module("Custom.NanoFXv2.NanoFX_Config")
    assert cfg.sFX_Enabled == 1


def test_other_custom_packages_still_resolve_from_mods(tmp_path, _pop):
    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "__init__.py", "")
    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "ZZTestShip.py", "MARK = 7\n")
    mods.configure(mods.build_index(tmp_path))
    _pop.extend(["Custom.Ships", "Custom.Ships.ZZTestShip"])
    m = importlib.import_module("Custom.Ships.ZZTestShip")
    assert m.MARK == 7


def test_unprovided_submodule_imports_and_logs_once(capsys):
    m = importlib.import_module("Custom.NanoFXv2.WarpFX.AI.NanoWarp")
    assert m.NanoWarp(1, 2) is None
    assert m.NanoWarp() is None
    err = capsys.readouterr().err
    assert err.count("NanoFX effect API not supported: Custom.NanoFXv2.WarpFX.AI.NanoWarp.NanoWarp") == 1
    assert claimed.unsupported_calls() == ["Custom.NanoFXv2.WarpFX.AI.NanoWarp.NanoWarp"]


def test_non_claimed_names_are_not_claimed():
    assert claimed.claimed_spec("Custom.Ships.Foo") is None
    assert claimed.claimed_spec("Custom") is None
    assert claimed.claimed_spec("App") is None


@pytest.fixture
def _pop():
    names = []
    yield names
    for n in reversed(names):
        sys.modules.pop(n, None)


def test_from_import_of_unprovided_submodule_then_call(capsys):
    from Custom.NanoFXv2.WarpFX import WarpFX_GUI
    assert WarpFX_GUI.GetWarpSpeed() is None
    assert WarpFX_GUI.SetupWarpSpeedButtons(9) is None
    assert "NanoFX effect API not supported: Custom.NanoFXv2.WarpFX.WarpFX_GUI.GetWarpSpeed" in capsys.readouterr().err
