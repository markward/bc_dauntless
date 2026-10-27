"""engine.core.case_paths: BC content resolves regardless of spelled case.

The live case is GalaxyBridge.py's `import DBridgeProperties` against a file
named dbridgeproperties.py, which only fails on a case-sensitive filesystem.
"""

from engine.core import case_paths


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
    assert (case_paths.resolve(root, "Bridge/DBridgeProperties.py")
            == root / "Bridge" / "dbridgeproperties.py")


def test_resolve_folds_directory_components_too(tmp_path):
    root = _tree(tmp_path)
    assert (case_paths.resolve(root, "bridge/characters/__init__.py")
            == root / "Bridge" / "Characters" / "__init__.py")


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
    assert paths.game_asset("data/Models/Sets/DBridge/DBridge.nif") == nif
    # A path that exists in no case comes back exactly as spelled.
    assert (paths.game_asset("data/Models/Missing.nif")
            == tmp_path / "data/Models/Missing.nif")
