"""settings.json, bridges.json and quickbattle presets follow config_dir()."""
import sys

import pytest

from engine import paths, settings_store


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dauntless"])
    paths._reset_write_failure_reports()
    yield
    paths._reset_write_failure_reports()


def test_settings_bridges_presets_land_in_config_dir(monkeypatch, tmp_path):
    from engine import bridge_selection
    from engine.quickbattle import presets
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    cfg = paths.config_dir()
    assert cfg == tmp_path
    settings_store.SettingsStore().set("gameplay", "probe", 1)
    assert (cfg / "settings.json").is_file()
    settings_store.SettingsStore(
        bridge_selection.default_bridges_path()).set("pins", "probe", 1)
    settings_store.SettingsStore(
        presets.default_presets_path()).set("presets", "probe", 1)
    assert (cfg / "bridges.json").is_file()
    assert (cfg / "quickbattle_presets.json").is_file()


def test_checkout_settings_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    assert settings_store.default_settings_path() == root / "settings.json"


def test_failed_save_is_reported_not_raised(monkeypatch, tmp_path, capsys):
    afile = tmp_path / "afile"
    afile.write_text("x")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(afile))
    store = settings_store.SettingsStore()
    store._save()
    assert "could not write" in capsys.readouterr().err
