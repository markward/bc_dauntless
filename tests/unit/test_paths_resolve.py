"""Resolution precedence, caching, and the failure message.

`resolve()` is pure — it takes argv, env and the store explicitly, writes
nothing, and touches no global. Every test drives it directly.
"""
import json
from pathlib import Path

import pytest

from engine import paths
from engine.settings_store import SettingsStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_cache():
    """paths caches a Resolution in a module global.

    Save and RESTORE rather than clearing: tests/conftest.py configures the
    session's real resolution at import, and leaving None behind would make
    every later test file re-resolve from ambient state.
    """
    saved = paths._RESOLUTION
    paths.configure(None)
    yield
    paths.configure(saved)


def _store_with(tmp_path, **kv):
    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    for k, v in kv.items():
        store.set("paths", k, str(v))
    return store


# --- precedence -------------------------------------------------------------

def test_cli_flag_wins(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game="/nowhere", sdk="/nowhere")
    res = paths.resolve(
        argv=["--game-dir", str(game), "--sdk-dir", str(sdk)],
        env={"DAUNTLESS_GAME_DIR": "/also-nowhere"},
        store=store,
    )
    assert res.game == game
    assert res.game_source == "cli"
    assert res.sdk_source == "cli"


def test_cli_flag_accepts_equals_form(fake_bc_install):
    game, _sdk = fake_bc_install
    res = paths.resolve(argv=[f"--game-dir={game}"], env={}, store=None)
    assert res.game == game
    assert res.game_source == "cli"


def test_env_beats_settings(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game="/nowhere", sdk=str(sdk))
    res = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game)}, store=store)
    assert res.game == game
    assert res.game_source == "env"
    assert res.sdk == sdk
    assert res.sdk_source == "settings"


def test_settings_beats_the_project_default(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game=game, sdk=sdk)
    res = paths.resolve(argv=[], env={}, store=store)
    assert res.game == game
    assert res.game_source == "settings"


def test_the_two_roots_resolve_independently(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    assert res.game_source == "cli"
    assert res.sdk_source == "settings"


# --- the load-bearing precedence rule ---------------------------------------

def test_a_set_but_invalid_source_is_an_error_not_a_fallthrough(fake_bc_install, tmp_path):
    """--game-dir /typo must be reported, NOT silently replaced by a stale
    settings.json — that would run a different install than was asked for."""
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, game=game, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", "/definitely/not/here"], env={}, store=store)
    assert not res.ok
    assert res.game is None
    assert res.game_source == "cli"
    assert res.game_validation is not None
    assert not res.game_validation.ok
    assert str(res.game_validation.root) == "/definitely/not/here"


def test_an_absent_project_default_is_not_an_error(tmp_path, monkeypatch):
    """Source 4 is a fallback: its absence means 'nothing configured'."""
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    assert not res.ok
    assert res.game is None
    assert res.game_source == ""
    assert res.game_validation is None


def test_the_project_default_is_used_when_present(tmp_path, monkeypatch):
    for rel in ("game/data", "game/data/Models", "game/data/Textures", "game/data/Icons"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    assert res.game == tmp_path / "game"
    assert res.game_source == "project"


# --- stored form ------------------------------------------------------------

def test_stored_paths_expand_user_and_normalise(fake_bc_install, tmp_path, monkeypatch):
    game, _sdk = fake_bc_install
    monkeypatch.setenv("HOME", str(game.parent))
    res = paths.resolve(argv=["--game-dir", "~/game/../game"], env={}, store=None)
    assert res.game == game


def test_symlinks_are_not_followed(fake_bc_install, tmp_path):
    game, _sdk = fake_bc_install
    link = tmp_path / "via-link"
    link.symlink_to(game, target_is_directory=True)
    res = paths.resolve(argv=["--game-dir", str(link)], env={}, store=None)
    assert res.game == link
    assert res.game != game


# --- persistence ------------------------------------------------------------

def test_persist_writes_only_cli_sourced_roots(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    store = _store_with(tmp_path, sdk=sdk)
    res = paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    paths.persist(res, store)
    doc = json.loads((tmp_path / "settings.json").read_text())
    assert doc["paths"]["game"] == str(game)


def test_persist_never_writes_an_env_sourced_root(fake_bc_install, tmp_path):
    """DAUNTLESS_SDK_DIR=/fixtures pytest must not mutate a real config."""
    game, sdk = fake_bc_install
    store = _store_with(tmp_path)
    res = paths.resolve(argv=[], env={"DAUNTLESS_GAME_DIR": str(game),
                                     "DAUNTLESS_SDK_DIR": str(sdk)}, store=store)
    paths.persist(res, store)
    # The store is write-through: with nothing to persist the file is never
    # created at all, which is itself the assertion.
    settings = tmp_path / "settings.json"
    doc = json.loads(settings.read_text()) if settings.exists() else {}
    assert doc.get("paths", {}) == {}


def test_persist_never_writes_an_invalid_path(tmp_path):
    store = _store_with(tmp_path)
    res = paths.resolve(argv=["--game-dir", "/typo"], env={}, store=store)
    paths.persist(res, store)
    settings = tmp_path / "settings.json"
    doc = json.loads(settings.read_text()) if settings.exists() else {}
    assert "game" not in doc.get("paths", {})


def test_resolve_itself_writes_nothing(fake_bc_install, tmp_path):
    game, _sdk = fake_bc_install
    settings = tmp_path / "settings.json"
    store = _store_with(tmp_path)
    before = settings.read_text() if settings.exists() else None
    paths.resolve(argv=["--game-dir", str(game)], env={}, store=store)
    after = settings.read_text() if settings.exists() else None
    assert after == before


# --- cache and accessors ----------------------------------------------------

def test_accessors_read_the_configured_resolution(fake_bc_install):
    game, sdk = fake_bc_install
    paths.configure(paths.resolve(argv=["--game-dir", str(game),
                                        "--sdk-dir", str(sdk)], env={}, store=None))
    assert paths.game_root() == game
    assert paths.sdk_root() == sdk
    assert paths.sdk_scripts() == sdk / "Build" / "scripts"
    assert paths.sdk_data() == sdk / "Build" / "Data"
    assert paths.game_asset("data/rough.tga") == game / "data" / "rough.tga"


def test_game_asset_accepts_a_path_as_well_as_a_string(fake_bc_install):
    from pathlib import Path
    game, sdk = fake_bc_install
    paths.configure(paths.resolve(argv=["--game-dir", str(game),
                                        "--sdk-dir", str(sdk)], env={}, store=None))
    assert paths.game_asset(Path("data") / "rough.tga") == game / "data" / "rough.tga"


def test_an_unresolved_root_raises_with_the_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    paths.configure(paths.resolve(argv=[], env={}, store=_store_with(tmp_path)))
    with pytest.raises(paths.PathsUnresolved) as exc:
        paths.game_root()
    assert "cannot locate your Bridge Commander install" in str(exc.value)


# --- the failure message ----------------------------------------------------

def test_describe_failure_names_every_source_it_consulted(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    res = paths.resolve(argv=[], env={}, store=_store_with(tmp_path))
    text = paths.describe_failure(res)
    assert "--game-dir" in text
    assert "DAUNTLESS_GAME_DIR" in text
    assert "settings.json" in text
    assert "--sdk-dir" in text
    assert "DAUNTLESS_SDK_DIR" in text


def test_describe_failure_reports_missing_markers_and_the_hint(fake_bc_install, tmp_path):
    game, sdk = fake_bc_install
    res = paths.resolve(argv=["--game-dir", str(game.parent),
                              "--sdk-dir", str(sdk)], env={}, store=None)
    text = paths.describe_failure(res)
    assert "data/Models" in text
    assert "contains 'game'" in text
    assert str(game) in text


def test_describe_failure_is_empty_for_a_good_resolution(fake_bc_install):
    game, sdk = fake_bc_install
    res = paths.resolve(argv=["--game-dir", str(game),
                              "--sdk-dir", str(sdk)], env={}, store=None)
    assert res.ok
    assert paths.describe_failure(res) == ""


def test_resolve_works_without_conftest_on_the_path(tmp_path):
    """A bare `uv run python tools/foo.py` must reach settings.json.

    resolve() -> settings_store -> dev_mode -> `import _dauntless_host`, which
    lives in build/python/. Only conftest used to add that directory, so every
    tools/ script would have died with ModuleNotFoundError instead of a path
    error. engine/__init__ now completes the job its docstring claims.
    """
    import subprocess
    import sys as _sys
    result = subprocess.run(
        [_sys.executable, "-c",
         "import sys; sys.path[:] = [p for p in sys.path if 'build/python' not in p];"
         "from engine import paths; print(paths.resolve(argv=[], env={}).game_source)"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
