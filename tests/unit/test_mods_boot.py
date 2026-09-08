from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def test_install_builds_classifies_and_configures(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    (tmp_path / "g").mkdir(); (tmp_path / "s").mkdir()
    _touch(tmp_path / "mods" / "M" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "Custom" / "x.py",)
    (tmp_path / "mods" / "M" / "Scripts" / "Custom" / "x.py").write_text(
        "import Foundation\n")

    idx = mods.install(argv=["--mods-dir", str(tmp_path / "mods")], env={})

    assert mods.current() is idx
    assert idx.lookup("data/a.nif") is not None
    assert {m.name: m.requires for m in idx.mods}["M"] == ["Foundation"]


def test_install_with_no_mods_dir_is_an_empty_index(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    idx = mods.install(argv=["--mods-dir", str(tmp_path / "absent")], env={})
    assert idx.files == {}
    assert mods.describe(idx) == ""


def test_renderer_override_payload_is_game_targets_only(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "g")
    monkeypatch.setattr(paths, "sdk_scripts", lambda: tmp_path / "s")
    (tmp_path / "g").mkdir(); (tmp_path / "s").mkdir()
    _touch(tmp_path / "mods" / "M" / "Data" / "a.nif")
    _touch(tmp_path / "mods" / "M" / "Scripts" / "b.py")
    idx = mods.install(argv=["--mods-dir", str(tmp_path / "mods")], env={})
    payload = mods.renderer_overrides(idx)
    assert list(payload) == ["data/a.nif"]
    assert payload["data/a.nif"].endswith("a.nif")
