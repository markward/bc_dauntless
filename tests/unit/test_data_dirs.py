"""Data-dir mode, override and per-kind accessors in engine/paths.py."""
import sys
from pathlib import Path

import pytest

from engine import paths


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["dauntless"])
    paths._reset_write_failure_reports()
    yield
    paths._reset_write_failure_reports()


def _packaged_root(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "install"
    root.mkdir()
    (root / paths.PACKAGED_MARKER).write_text("{}")
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    return root


def test_checkout_layout_is_todays_layout(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    assert paths.data_layout() == ("checkout", root)
    assert paths.config_dir() == root
    assert paths.saves_dir() == root / "saves"
    assert paths.mods_default_dir() == root / "mods"
    assert paths.cache_dir() == root / "cache"
    assert paths.log_dir() == root
    assert paths.log_file_path() == root / "logs" / "dauntless.log"
    assert paths.hull_volume_cache_root() == root / "cache" / "hull_volumes"


def test_override_flag_beats_env_beats_marker(monkeypatch, tmp_path):
    _packaged_root(monkeypatch, tmp_path)
    flag_dir = tmp_path / "flag"
    env_dir = tmp_path / "env"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(env_dir))
    monkeypatch.setattr(sys, "argv", ["dauntless", "--data-dir", str(flag_dir)])
    assert paths.data_layout() == ("override", flag_dir)
    monkeypatch.setattr(sys, "argv", ["dauntless"])
    assert paths.data_layout() == ("override", env_dir)
    monkeypatch.delenv(paths.DATA_DIR_ENV)
    assert paths.data_layout() == ("packaged", None)


def test_empty_flag_counts_as_unset(monkeypatch, tmp_path):
    env_dir = tmp_path / "env"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(env_dir))
    assert paths.data_dir_override(argv=["--data-dir="]) == env_dir
    assert paths.data_dir_override(argv=["--data-dir"]) == env_dir


def test_override_uses_checkout_layout(monkeypatch, tmp_path):
    d = tmp_path / "d"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(d))
    assert paths.config_dir() == d
    assert paths.saves_dir() == d / "saves"
    assert paths.mods_default_dir() == d / "mods"
    assert paths.cache_dir() == d / "cache"
    assert paths.log_file_path() == d / "logs" / "dauntless.log"


def test_packaged_uses_os_user_dirs(monkeypatch, tmp_path):
    _packaged_root(monkeypatch, tmp_path)
    fake = {k: tmp_path / "u" / k
            for k in ("config", "saves", "mods", "cache", "logs")}
    monkeypatch.setattr(paths, "os_user_dirs", lambda *a, **k: fake)
    assert paths.config_dir() == fake["config"]
    assert paths.saves_dir() == fake["saves"]
    assert paths.mods_default_dir() == fake["mods"]
    assert paths.cache_dir() == fake["cache"]
    assert paths.log_dir() == fake["logs"]
    assert paths.log_file_path() == fake["logs"] / "dauntless.log"
    assert paths.hull_volume_cache_root() == fake["cache"] / "hull_volumes"


def test_resolved_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "one"))
    first = paths.config_dir()
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "two"))
    assert paths.config_dir() == tmp_path / "two" != first


def test_accessors_create_nothing(monkeypatch, tmp_path):
    d = tmp_path / "missing"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(d))
    for fn in (paths.config_dir, paths.saves_dir, paths.mods_default_dir,
               paths.cache_dir, paths.log_dir, paths.log_file_path,
               paths.hull_volume_cache_root):
        fn()
    assert not d.exists()


def test_report_write_failure_prints_once_per_path(capsys):
    paths.report_write_failure("/a/x", OSError("boom"))
    paths.report_write_failure("/a/x", OSError("boom"))
    paths.report_write_failure("/b/y", PermissionError("nope"))
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 2
    assert err[0] == "[dauntless] could not write /a/x: OSError: boom"
    assert "/b/y" in err[1] and "PermissionError" in err[1]


def test_override_pointing_at_a_file_reports_and_continues(
        monkeypatch, tmp_path, capsys):
    from engine import settings_store
    # Any write that leaks past the override lands in tmp,
    # never in the real checkout.
    leak = tmp_path / "leak"
    leak.mkdir()
    monkeypatch.setattr(paths, "PROJECT_ROOT", leak)
    afile = tmp_path / "afile"
    afile.write_text("x")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(afile))
    settings_store.SettingsStore().set("gameplay", "probe", 1)
    assert str(afile) in capsys.readouterr().err
