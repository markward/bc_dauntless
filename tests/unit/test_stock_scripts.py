"""engine.stock_scripts: which stock modules exist, where they are on disk,
and how they become a module AST (spec 2026-11-11-no-sdk-runtime §4.1-4.2).

Fake trees with an injected manifest, except where real retail bytes are
needed (a lift, a code object), which come from the configured install.
"""
import ast
import hashlib

import pytest

from engine import paths, py15, stock_scripts
from engine.core import case_paths
from tests.helpers import write_audit
from tests.helpers.bc_assets import require_game_dir

E1M1 = "Maelstrom/Episode1/E1M1/E1M1.pyc"
H = "0" * 32


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _put(root, rel, data=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _retail_pyc(rel=E1M1):
    scripts = require_game_dir("scripts")
    found = case_paths.resolve(scripts, rel)
    if found is None:
        pytest.skip(f"BC assets not available: scripts/{rel}")
    return found


@pytest.fixture(autouse=True)
def _reset():
    # tests/conftest.py registers the SDK tutorial as a fixture tree at
    # import; these tests start from none, and its per-test reset puts it
    # back afterwards.
    stock_scripts.clear_fixture_trees()
    yield
    stock_scripts.configure(None, None)
    stock_scripts.clear_fixture_trees()


def test_find_returns_listed_modules_and_packages(tmp_path):
    _put(tmp_path, "AI/Preprocessors.pyc")
    _put(tmp_path, "Bridge/__init__.pyc")
    stock_scripts.configure({"AI/Preprocessors.pyc": [H],
                             "Bridge/__init__.pyc": [H]}, tmp_path)
    sf = stock_scripts.find("ai/preprocessors")
    assert sf is not None
    assert sf.path.as_posix().endswith("AI/Preprocessors.pyc")
    assert sf.rel == "AI/Preprocessors"
    assert not sf.is_package and not sf.is_fixture
    pkg = stock_scripts.find("Bridge")
    assert pkg.is_package and pkg.rel == "Bridge"
    assert pkg.path.as_posix().endswith("Bridge/__init__.pyc")


def test_unlisted_files_in_the_install_are_invisible(tmp_path):
    _put(tmp_path, "QuickBattle/QuickBattle.pyc")
    _put(tmp_path, "QuickBattle/QuickBattle.py", b"def X(): pass\n")
    _put(tmp_path, "ships/MyShip.pyc")
    _put(tmp_path, "ships/Galaxy.pyc")
    stock_scripts.configure({"ships/Galaxy.pyc": [H]}, tmp_path)
    assert stock_scripts.find("QuickBattle/QuickBattle") is None
    assert stock_scripts.find("ships/MyShip") is None
    assert stock_scripts.find_by_leaf("MyShip") == []
    assert stock_scripts.find("ships/Galaxy") is not None
    assert [sf.rel for sf in stock_scripts.children("ships")] == ["ships/Galaxy"]


def test_lookup_is_case_insensitive_on_disk(tmp_path):
    on_disk = _put(tmp_path, "Scripts/Ships/Galaxy.pyc")
    stock_scripts.configure({"ships/Galaxy.pyc": [H]}, tmp_path / "Scripts")
    sf = stock_scripts.find("ships/Galaxy")
    assert sf is not None and sf.path.exists()
    assert sf.path.samefile(on_disk)
    assert sf.rel == "ships/Galaxy"
    again = stock_scripts.find("SHIPS/galaxy")
    assert again is not None and again.path.samefile(on_disk)


def test_find_by_leaf_sorted_and_excludes_init(tmp_path):
    for rel in ("Tactical/Interface/Foo.pyc", "AI/Foo.pyc", "Foo/__init__.pyc",
                "AI/Bar.pyc"):
        _put(tmp_path, rel)
    stock_scripts.configure({"Tactical/Interface/Foo.pyc": [H], "AI/Foo.pyc": [H],
                             "Foo/__init__.pyc": [H], "AI/Bar.pyc": [H]},
                            tmp_path)
    assert [sf.rel for sf in stock_scripts.find_by_leaf("foo")] == [
        "AI/Foo", "Tactical/Interface/Foo"]
    assert stock_scripts.find_by_leaf("__init__") == []


def test_children_lists_direct_children_only(tmp_path):
    for rel in ("ships/Galaxy.pyc", "ships/Hardpoints/galaxy.pyc",
                "ships/Hardpoints/__init__.pyc", "ships/__init__.pyc"):
        _put(tmp_path, rel)
    stock_scripts.configure({rel: [H] for rel in (
        "ships/Galaxy.pyc", "ships/Hardpoints/galaxy.pyc",
        "ships/Hardpoints/__init__.pyc", "ships/__init__.pyc")}, tmp_path)
    got = {(sf.rel, sf.is_package) for sf in stock_scripts.children("Ships")}
    assert got == {("ships/Galaxy", False), ("ships/Hardpoints", True)}


def test_is_stock_accepts_any_extension_and_case(tmp_path):
    stock_scripts.configure({"ships/Galaxy.pyc": [H],
                             "Bridge/__init__.pyc": [H]}, tmp_path)
    for rel in ("ships/galaxy", "ships/galaxy.py", "SHIPS/Galaxy.PYC",
                "ships\\Galaxy.py", "Bridge/__init__.py", "bridge"):
        assert stock_scripts.is_stock(rel), rel
    assert not stock_scripts.is_stock("ships/MyShip.py")
    assert not stock_scripts.is_stock("ships")


def test_top_level_functions_reads_bytecode_without_lifting(tmp_path, monkeypatch):
    real = _retail_pyc()
    root = real.parents[3]
    stock_scripts.configure({E1M1: [H]}, root)

    def _no_lift(*_a, **_k):
        raise AssertionError("top_level_functions must not lift")
    monkeypatch.setattr(py15, "lift_file", _no_lift)
    monkeypatch.setattr(py15, "lift", _no_lift)
    fns = stock_scripts.top_level_functions(
        stock_scripts.find("Maelstrom/Episode1/E1M1/E1M1"))
    assert "Initialize" in fns and fns["Initialize"][0] == "pMission"
    assert all(not name.startswith("<") for name in fns)


def test_top_level_functions_skips_class_bodies():
    real = _retail_pyc("StylizedWindow.pyc")
    stock_scripts.configure({"StylizedWindow.pyc": [H]}, real.parent)
    fns = stock_scripts.top_level_functions(stock_scripts.find("StylizedWindow"))
    assert "BaseStyle" not in fns


def test_top_level_functions_of_a_fixture_reads_the_source(tmp_path):
    _put(tmp_path, "Custom/Tutorial/M1.py",
         b"class C:\n\tdef m(self): pass\n"
         b"def Initialize(pMission, x=1):\n\tpass\n")
    stock_scripts.configure({}, tmp_path / "install")
    stock_scripts.add_fixture_tree(tmp_path, "Custom/Tutorial")
    fns = stock_scripts.top_level_functions(stock_scripts.find("Custom/Tutorial/M1"))
    assert fns == {"Initialize": ("pMission", "x")}


def test_unknown_hash_warns_once_and_loads(tmp_path, capsys):
    data = _retail_pyc().read_bytes()
    _put(tmp_path, E1M1, data)
    stock_scripts.configure({E1M1: ["f" * 32]}, tmp_path)
    sf = stock_scripts.find("Maelstrom/Episode1/E1M1/E1M1")
    t1 = stock_scripts.load_tree(str(sf.path), "Maelstrom.Episode1.E1M1.E1M1")
    t2 = stock_scripts.load_tree(str(sf.path), "Maelstrom.Episode1.E1M1.E1M1")
    assert isinstance(t1, ast.Module) and isinstance(t2, ast.Module)
    out = capsys.readouterr().out
    line = ("[stock-scripts] scripts/%s differs from every known retail copy "
            "(the install may be modded); loading it anyway" % E1M1)
    assert out.count(line) == 1


def test_known_hash_is_silent(tmp_path, capsys):
    data = _retail_pyc().read_bytes()
    _put(tmp_path, E1M1, data)
    stock_scripts.configure({E1M1: ["f" * 32, _hash(data)]}, tmp_path)
    sf = stock_scripts.find("Maelstrom/Episode1/E1M1/E1M1")
    tree = stock_scripts.load_tree(str(sf.path), "Maelstrom.Episode1.E1M1.E1M1")
    assert isinstance(tree, ast.Module)
    assert "[stock-scripts]" not in capsys.readouterr().out


def test_unliftable_stock_raises_stock_script_error_naming_the_file(tmp_path):
    bad = _put(tmp_path, "Broken.pyc", b"not bytecode at all")
    stock_scripts.configure({"Broken.pyc": [_hash(b"not bytecode at all")]},
                            tmp_path)
    sf = stock_scripts.find("Broken")
    with pytest.raises(stock_scripts.StockScriptError) as info:
        stock_scripts.load_tree(str(sf.path), "Broken")
    assert isinstance(info.value, ImportError)
    assert str(info.value.path) == str(bad)
    assert "Broken.pyc" in str(info.value)


def test_missing_listed_file_raises_stock_script_error_naming_it(tmp_path):
    stock_scripts.configure({"Gone.pyc": [H]}, tmp_path)
    sf = stock_scripts.find("Gone")
    assert sf is not None and not sf.path.exists()
    with pytest.raises(stock_scripts.StockScriptError) as info:
        stock_scripts.load_tree(str(sf.path), "Gone")
    assert "Gone.pyc" in str(info.value.path)


def test_fixture_tree_modules_resolve_after_the_manifest(tmp_path):
    install = tmp_path / "install"
    listed = _put(install, "Custom/Tutorial/Listed.pyc")
    sdk = tmp_path / "sdk_scripts"
    _put(sdk, "Custom/Tutorial/__init__.py", b"")
    _put(sdk, "Custom/Tutorial/Tutorial.py", b"def Initialize(pMission):\n\tpass\n")
    _put(sdk, "Custom/Tutorial/Listed.py", b"")
    _put(sdk, "Other/Outside.py", b"")
    stock_scripts.configure({"Custom/Tutorial/Listed.pyc": [H]}, install)
    stock_scripts.add_fixture_tree(sdk, "Custom/Tutorial")

    sf = stock_scripts.find("custom/tutorial/tutorial")
    assert sf.is_fixture and sf.rel == "Custom/Tutorial/Tutorial"
    assert sf.path == sdk / "Custom/Tutorial/Tutorial.py"
    assert stock_scripts.find("Custom/Tutorial").is_package
    assert stock_scripts.find("Other/Outside") is None
    # A fixture never shadows a listed module.
    shadow = stock_scripts.find("Custom/Tutorial/Listed")
    assert not shadow.is_fixture and shadow.path.samefile(listed)
    assert [s.rel for s in stock_scripts.find_by_leaf("Listed")] == [
        "Custom/Tutorial/Listed"]
    assert not stock_scripts.find_by_leaf("Listed")[0].is_fixture
    # Fixtures are not stock.
    assert not stock_scripts.is_stock("Custom/Tutorial/Tutorial.py")
    # Fixture source loads through the 1.5 source fixer.
    tree = stock_scripts.load_tree(str(sf.path), "Custom.Tutorial.Tutorial")
    assert isinstance(tree.body[0], ast.FunctionDef)

    stock_scripts.clear_fixture_trees()
    assert stock_scripts.find("Custom/Tutorial/Tutorial") is None


def test_fixture_tgl_roots_round_trip(tmp_path):
    assert stock_scripts.fixture_tgl_roots() == ()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    stock_scripts.add_fixture_tree(a, "Custom/Tutorial", tgl_root=a / "TGL")
    stock_scripts.add_fixture_tree(b, "Custom/Other")
    assert stock_scripts.fixture_tgl_roots() == (a / "TGL",)
    stock_scripts.clear_fixture_trees()
    assert stock_scripts.fixture_tgl_roots() == ()


def test_synthetic_packages_names_custom():
    assert stock_scripts.SYNTHETIC_PACKAGES == ("Custom",)


def test_default_configuration_uses_the_committed_manifest(tmp_path, monkeypatch):
    from engine import paths
    _put(tmp_path, "MissionLib.pyc")
    monkeypatch.setattr(paths, "stock_scripts", lambda: tmp_path)
    stock_scripts.configure(None, None)
    sf = stock_scripts.find("missionlib")
    assert sf is not None and sf.path == tmp_path / "MissionLib.pyc"
    assert stock_scripts.find("App") is None


def test_no_lifted_text_written(tmp_path):
    data = _retail_pyc().read_bytes()
    _put(tmp_path, E1M1, data)
    stock_scripts.configure({E1M1: ["f" * 32]}, tmp_path)
    sf = stock_scripts.find("Maelstrom/Episode1/E1M1/E1M1")
    write_audit.install_once()
    with write_audit.recording() as records:
        stock_scripts.load_tree(str(sf.path), "Maelstrom.Episode1.E1M1.E1M1")
    assert records == []


def test_lookup_folds_through_case_paths(tmp_path, monkeypatch):
    # Filesystem-independent: macOS cannot tell a right fold from a wrong one.
    miscased = tmp_path / "SHIPS" / "galaxy.PYC"
    seen = []

    def _resolve(base, rel):
        seen.append(rel)
        return miscased if rel == "ships/Galaxy.pyc" else None
    monkeypatch.setattr(case_paths, "resolve", _resolve)
    stock_scripts.configure({"ships/Galaxy.pyc": [H]}, tmp_path)
    sf = stock_scripts.find("SHIPS/GALAXY")
    assert sf.path == miscased and sf.rel == "ships/Galaxy"
    assert seen == ["ships/Galaxy.pyc"]


def test_find_by_leaf_does_not_walk_every_entry(tmp_path):
    stock_scripts.configure({"AI/Foo.pyc": [H], "AI/Bar.pyc": [H],
                             "Tactical/Foo.pyc": [H]}, tmp_path)
    index = stock_scripts._current()

    class _NoWalk(dict):
        def values(self):
            raise AssertionError("find_by_leaf must use the leaf index")
        items = values
        __iter__ = values
    index.entries = _NoWalk(index.entries)
    assert [sf.rel for sf in stock_scripts.find_by_leaf("FOO")] == [
        "AI/Foo", "Tactical/Foo"]
    assert stock_scripts.find_by_leaf("missing") == []


def test_scripts_folder_lookup_is_memoised_per_game_root(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    _put(a, "scripts/X.pyc")
    _put(b, "Scripts/X.pyc")
    root = [a]
    monkeypatch.setattr(paths, "game_root", lambda: root[0])
    calls = []
    real = case_paths.resolve
    monkeypatch.setattr(case_paths, "resolve",
                        lambda base, rel: calls.append(rel) or real(base, rel))
    stock_scripts.configure({"X.pyc": [H]}, None)
    assert stock_scripts.find("X").path.samefile(a / "scripts/X.pyc")
    stock_scripts.find("X")
    stock_scripts.is_stock("X")
    assert calls.count("scripts") == 1
    root[0] = b          # a re-configured root is followed (resolve-at-use)
    assert stock_scripts.find("X").path.samefile(b / "Scripts/X.pyc")
    assert calls.count("scripts") == 2


def test_top_level_functions_of_a_missing_file_names_it(tmp_path):
    stock_scripts.configure({"Gone.pyc": [H]}, tmp_path)
    with pytest.raises(stock_scripts.StockScriptError) as info:
        stock_scripts.top_level_functions(stock_scripts.find("Gone"))
    assert "Gone.pyc" in str(info.value) and "Gone.pyc" in info.value.path


def test_top_level_functions_of_a_bad_pyc_names_it(tmp_path):
    _put(tmp_path, "Broken.pyc", b"not bytecode at all")
    stock_scripts.configure({"Broken.pyc": [H]}, tmp_path)
    with pytest.raises(stock_scripts.StockScriptError) as info:
        stock_scripts.top_level_functions(stock_scripts.find("Broken"))
    assert "Broken.pyc" in str(info.value) and "Broken.pyc" in info.value.path


def test_load_tree_refuses_a_py_that_is_not_a_fixture(tmp_path):
    stray = _put(tmp_path, "QuickBattle/QuickBattle.py", b"def X(): pass\n")
    stock_scripts.configure({}, tmp_path)
    with pytest.raises(stock_scripts.StockScriptError) as info:
        stock_scripts.load_tree(str(stray), "QuickBattle.QuickBattle")
    assert info.value.path == str(stray)
