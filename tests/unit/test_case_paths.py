"""engine.core.case_paths: BC content resolves regardless of spelled case.

The live case is GalaxyBridge.py's `import DBridgeProperties` against a file
named dbridgeproperties.py, which only fails on a case-sensitive filesystem.

The tests compare file IDENTITY, not spelling. An exact-case match is always
tried first, so on a case-insensitive filesystem (macOS by default) the path
comes back as spelled, which is the same file; on Linux it must come back as
the on-disk spelling, because the spelled path does not exist there.
"""

from pathlib import Path

from engine.core import case_paths


def _same_file(found, expected):
    return found is not None and found.exists() and found.samefile(expected)


def _tree(tmp_path):
    (tmp_path / "Bridge" / "Characters").mkdir(parents=True)
    (tmp_path / "Bridge" / "dbridgeproperties.py").write_text("")
    (tmp_path / "Bridge" / "Characters" / "__init__.py").write_text("")
    (tmp_path / "Exact.py").write_text("")
    return tmp_path


def test_resolve_prefers_the_exact_spelling(tmp_path):
    root = _tree(tmp_path)
    assert case_paths.resolve(root, "Exact.py") == root / "Exact.py"


def test_resolve_matches_a_differently_cased_file(tmp_path):
    root = _tree(tmp_path)
    assert _same_file(case_paths.resolve(root, "Bridge/DBridgeProperties.py"),
                      root / "Bridge" / "dbridgeproperties.py")


def test_resolve_folds_directory_components_too(tmp_path):
    root = _tree(tmp_path)
    assert _same_file(case_paths.resolve(root, "bridge/characters/__init__.py"),
                      root / "Bridge" / "Characters" / "__init__.py")


def test_resolve_returns_none_when_nothing_matches(tmp_path):
    root = _tree(tmp_path)
    assert case_paths.resolve(root, "Bridge/Missing.py") is None
    assert case_paths.resolve(root, "Nowhere/Exact.py") is None


def test_rglob_py_finds_a_differently_cased_file_anywhere(tmp_path):
    root = _tree(tmp_path)
    assert (case_paths.rglob_py(root, "DBridgeProperties")
            == [root / "Bridge" / "dbridgeproperties.py"])
    assert case_paths.rglob_py(root, "Missing") == []


def test_game_asset_finds_a_differently_cased_stock_file(tmp_path, monkeypatch):
    from engine import mods, paths
    nif = tmp_path / "data" / "Models" / "Sets" / "DBridge" / "Dbridge.NIF"
    nif.parent.mkdir(parents=True)
    nif.write_text("")
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path)
    monkeypatch.setattr(mods, "game_override", lambda rel: None)
    assert _same_file(paths.game_asset("data/Models/Sets/DBridge/DBridge.nif"), nif)
    # A path that exists in no case comes back exactly as spelled.
    assert (paths.game_asset("data/Models/Missing.nif")
            == tmp_path / "data/Models/Missing.nif")


def test_bare_sdk_import_registers_under_the_on_disk_spelling(tmp_path,
                                                              monkeypatch):
    """`import DBridgeProperties` from Bridge/ reaches the Python 1.5
    implicit-relative fallback, which also registers the module under its
    dotted name. That name must follow the file on disk
    (`Bridge.dbridgeproperties`), not the import's spelling: on macOS the old
    rglob echoed the spelling back, so one file could become two modules
    under two names; on Linux it found nothing at all.

    Driven through tools/mission_harness.py's finder (the game's copy, which
    resolves its SDK root at use); test_sdk_finder_twins_stay_in_sync keeps
    tests/conftest.py's copy identical to it.
    """
    import tools.mission_harness as harness
    from engine import mods
    on_disk = tmp_path / "Bridge" / "zzcaseprobeprops.py"
    on_disk.parent.mkdir()
    on_disk.write_text("")
    monkeypatch.setattr(harness, "_sdk_scripts", lambda: tmp_path)
    monkeypatch.setattr(mods, "_INDEX", None)      # stock only, no mods
    spec = harness._SDKFinder().find_spec("ZZCaseProbeProps", None)
    assert spec is not None
    assert _same_file(Path(spec.origin), on_disk)
    assert spec.loader.also_register_as == "Bridge.zzcaseprobeprops"
