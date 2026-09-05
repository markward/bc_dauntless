"""SettingsStore — JSON persistence for Dauntless settings.

Section/key addressed and table-agnostic; the SETTINGS table lives in the
same module but these tests exercise only the file I/O half.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
import json
import stat

import pytest

from engine.settings_store import SCHEMA_VERSION, SettingsStore


def _store(tmp_path):
    return SettingsStore(path=tmp_path / "settings.json")


def test_round_trip_through_a_fresh_store(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "camera_shake", False)

    reloaded = _store(tmp_path)
    reloaded.load()
    assert reloaded.get("graphics", "camera_shake") is False


def test_missing_file_loads_clean(tmp_path):
    s = _store(tmp_path)
    s.load()                          # file does not exist
    assert s.has("graphics", "smaa") is False
    assert s.get("graphics", "smaa") is None


def test_corrupt_file_is_quarantined_and_load_does_not_raise(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json at all")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()
    assert (tmp_path / "settings.json.corrupt").read_text() == "{not json at all"


def test_non_object_json_is_also_treated_as_corrupt(tmp_path):
    # Valid JSON, wrong shape — a bare list would explode on .get() later.
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]")
    s = SettingsStore(path=path)
    s.load()

    assert s.has("graphics", "smaa") is False
    assert (tmp_path / "settings.json.corrupt").exists()


def test_unknown_sections_and_keys_survive_a_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "version": SCHEMA_VERSION,
        "graphics": {"smaa": True, "future_knob": 7},
        "paths": {"game_dir": "/somewhere"},
    }))
    s = SettingsStore(path=path)
    s.load()
    s.set("graphics", "smaa", False)

    on_disk = json.loads(path.read_text())
    assert on_disk["graphics"]["future_knob"] == 7
    assert on_disk["paths"] == {"game_dir": "/somewhere"}
    assert on_disk["graphics"]["smaa"] is False


def test_a_newer_schema_version_is_not_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION + 5,
                                "graphics": {"smaa": True}}))
    s = SettingsStore(path=path)
    s.load()
    assert s.get("graphics", "smaa") is True     # known keys still read
    s.set("graphics", "dust", False)

    assert json.loads(path.read_text())["version"] == SCHEMA_VERSION + 5


def test_reset_section_deletes_it(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    s.set("gameplay", "subtitles", False)

    s.reset_section("graphics")

    assert s.has("graphics", "smaa") is False
    assert s.has("gameplay", "subtitles") is True
    assert "graphics" not in json.loads((tmp_path / "settings.json").read_text())


def test_set_leaves_no_temp_file_behind(tmp_path):
    s = _store(tmp_path)
    s.load()
    s.set("graphics", "smaa", False)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_unwritable_location_does_not_raise(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    s = SettingsStore(path=ro / "settings.json")
    s.load()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)          # read + execute, no write
    try:
        s.set("graphics", "smaa", False)            # must not raise
        assert s.get("graphics", "smaa") is False   # in-memory value still holds
    finally:
        ro.chmod(stat.S_IRWXU)                      # restore so tmp_path cleans up
