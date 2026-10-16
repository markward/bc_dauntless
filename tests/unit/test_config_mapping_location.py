"""BC .cfg files (Options.cfg, Keybindings.cfg) resolve into config_dir()."""
import sys

import pytest

from engine import paths
from engine.appc.config_mapping import TGConfigMapping
from engine.input_map import InputMap


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dauntless"])
    paths._reset_write_failure_reports()
    yield
    paths._reset_write_failure_reports()


def test_bare_options_cfg_resolves_into_config_dir(monkeypatch, tmp_path):
    data = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(data))
    monkeypatch.chdir(elsewhere)
    cfg = TGConfigMapping()
    cfg.SetStringValue("S", "k", "v")
    assert cfg.SaveConfigFile("Options.cfg") == 1
    assert (paths.config_dir() / "Options.cfg").is_file()
    assert not (elsewhere / "Options.cfg").exists()


def test_keybindings_round_trip_in_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    a = InputMap()
    a.set(next(iter(a._map)), "F9")
    assert a.save() == 1
    assert (paths.config_dir() / "Keybindings.cfg").is_file()
    b = InputMap()
    b.load()
    assert b._map == a._map


def test_absolute_name_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    target = tmp_path / "abs" / "x.cfg"
    assert TGConfigMapping()._resolve_path(str(target)) == target


def test_backslash_names_are_converted(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert (TGConfigMapping()._resolve_path("sub\\Options.cfg")
            == paths.config_dir() / "sub" / "Options.cfg")


def test_checkout_options_cfg_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    assert TGConfigMapping()._resolve_path("Options.cfg") == root / "Options.cfg"


def test_failed_save_reports(monkeypatch, tmp_path, capsys):
    afile = tmp_path / "afile"
    afile.write_text("x")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(afile))
    cfg = TGConfigMapping()
    assert cfg.SaveConfigFile("Options.cfg") == 0
    assert cfg.SaveConfigFile("Options.cfg") == 0
    err = capsys.readouterr().err
    assert err.count("could not write") == 1
