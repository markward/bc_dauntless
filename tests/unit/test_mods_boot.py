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


def test_install_uses_explicit_roots_not_ambient_globals(monkeypatch, tmp_path):
    """Regression test for the Task 10 review finding: install() reaching
    classify() via paths.game_root()/paths.sdk_scripts() reads the GLOBAL
    paths._RESOLUTION, which a caller holding its own resolved roots (host_
    loop's boot sequence, passing resolution.game/resolution.sdk directly;
    or a test that monkeypatches paths.configure to a no-op the way
    tests/host/test_host_loop_first_run.py does) may leave stale or
    unconfigured. That leak let a live scan of the developer's real mods/
    directory, classified against their real ambient BC install, print from
    inside an unrelated test.

    Passing game_root/sdk_scripts explicitly must bypass the ambient
    accessors entirely -- proven here by making them raise if install() ever
    calls them, and by asserting the override was resolved against the
    PASSED root (not merely that nothing printed).
    """
    monkeypatch.setattr(paths, "configure", lambda resolution: None)

    def _must_not_be_called():
        raise AssertionError(
            "install() must use the passed game_root/sdk_scripts, never "
            "read them back through the ambient paths accessors")
    monkeypatch.setattr(paths, "game_root", _must_not_be_called)
    monkeypatch.setattr(paths, "sdk_scripts", _must_not_be_called)

    game = tmp_path / "g"
    sdk = tmp_path / "s"
    game.mkdir()
    sdk.mkdir()
    # A stock file the mod overrides -- classify() only records an override
    # if it resolves the mod's relative path against the PASSED root.
    _touch(game / "data" / "a.nif")
    _touch(tmp_path / "mods" / "M" / "Data" / "a.nif")

    idx = mods.install(argv=["--mods-dir", str(tmp_path / "mods")], env={},
                       game_root=game, sdk_scripts=sdk)

    assert idx.overrides == ["data/a.nif"]
