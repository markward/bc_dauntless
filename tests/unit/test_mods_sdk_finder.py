import ast
import importlib
import sys
from pathlib import Path

import pytest

from engine import mods, paths


def _touch(p: Path, body: str = "x = 1\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


@pytest.fixture
def _pop_after_test():
    """Names to remove from sys.modules once the test is done, in reverse
    order (submodule before its parent package). This suite is
    order-sensitive -- a real import must not leak module state into other
    tests, including tests/conftest.py's own _SDKFinder-backed suite."""
    names = []
    yield names
    for name in reversed(names):
        sys.modules.pop(name, None)


def test_sdk_override_returns_the_mod_module(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("ships/Fsteamr.py") is not None


def test_sdk_override_is_case_blind_both_ways(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "Fsteamr.py")
    mods.configure(mods.build_index(tmp_path))
    # BC's filesystem made Ships and ships one directory; so do we.
    assert mods.sdk_override("ships/Fsteamr.py") is not None
    assert mods.sdk_override("Ships/Fsteamr.py") is not None


def test_game_targeted_entries_do_not_leak_into_sdk_override(tmp_path):
    _touch(tmp_path / "M" / "Data" / "a.py")
    mods.configure(mods.build_index(tmp_path))
    assert mods.sdk_override("data/a.py") is None


def test_no_index_means_no_override(tmp_path):
    assert mods.sdk_override("ships/Fsteamr.py") is None


# --- Real import round-trips through _SDKFinder.find_spec ------------------
#
# The tests above exercise only the pure mods.sdk_override() lookup. These
# drive an actual `importlib.import_module` so the finder wiring added in
# tools/mission_harness.py and tests/conftest.py -- constructing the
# ModuleSpec/_SDKLoader, setting origin, and (package case) setting
# submodule_search_locations -- is under test too, not just read by eye.
#
# tests/conftest.py's pytest_configure() already installs _SDKFinder into
# sys.meta_path for the whole session, so no finder is installed here.
#
# Proof of provenance uses module.__spec__.origin rather than __file__: this
# loader builds a bare `ModuleSpec(name, loader, origin=...)`, which never
# sets `_set_fileattr` (confirmed empirically against a real SDK module --
# MissionLib.__file__ is absent even for an ordinary SDK import through this
# same finder). __spec__.origin is always populated by the import system
# regardless, and is the same value the finder used to build the spec, so it
# is the correct provenance check for this loader shape.

def test_sdk_override_wins_for_a_real_module_import(tmp_path, _pop_after_test):
    name = "_dauntless_test_sdk_override_leaf_mod"
    mod_file = tmp_path / "M" / "Scripts" / (name + ".py")
    _touch(mod_file, "MARKER = 'from-the-mod'\n")
    mods.configure(mods.build_index(tmp_path))
    _pop_after_test.append(name)

    module = importlib.import_module(name)

    assert module.MARKER == "from-the-mod"
    assert Path(module.__spec__.origin).resolve() == mod_file.resolve()


def test_sdk_override_wins_for_a_real_package_submodule_import(tmp_path, _pop_after_test):
    pkg = "_dauntless_test_sdk_override_pkg"
    pkg_dir = tmp_path / "M" / "Scripts" / pkg
    _touch(pkg_dir / "__init__.py", "MARKER = 'pkg-init'\n")
    _touch(pkg_dir / "leaf.py", "MARKER = 'pkg-leaf'\n")
    mods.configure(mods.build_index(tmp_path))
    _pop_after_test += [pkg, pkg + ".leaf"]

    package = importlib.import_module(pkg)

    assert package.MARKER == "pkg-init"
    assert Path(package.__spec__.origin).resolve() == (pkg_dir / "__init__.py").resolve()
    # This is the assertion that exercises submodule_search_locations: it is
    # what find_spec set on the returned package spec, and what the import
    # system in turn copies onto the live package's __path__.
    assert [Path(p).resolve() for p in package.__path__] == [pkg_dir.resolve()]

    submodule = importlib.import_module(pkg + ".leaf")

    assert submodule.MARKER == "pkg-leaf"
    assert Path(submodule.__spec__.origin).resolve() == (pkg_dir / "leaf.py").resolve()


# --- Python 1.5 implicit relative imports inside a MOD package -------------
#
# _FixImplicitRelativeImport used to derive its package from the file's
# ON-DISK path relative to the SDK scripts root. A mod file is never under
# that root, so relative_to() raised, the package came out None, and the
# transform was a silent no-op for every mod-loaded script -- while every
# other compatibility transform (_fix_py2_syntax, _FixDottedImport,
# _FixPy2Compare, ...) applied to mod files normally.
#
# The transform's own docstring cites QuickBattle, which the spec names as a
# module Foundation-style mods deliberately replace, so this was the one
# member of the set skipped for exactly the files that need it.

def test_a_mod_script_gets_python_1_5_implicit_relative_imports(
        tmp_path, _pop_after_test):
    """A bare `import Sibling` inside a mod's package binds the SIBLING
    MODULE, not the same-named package."""
    pkg = "_dauntless_test_mod_implicit_rel"
    pkg_dir = tmp_path / "M" / "Scripts" / pkg
    _touch(pkg_dir / "__init__.py", "MARKER = 'the-package'\n")
    # The collision BC's Python 1.5 resolved the other way: a package and a
    # module inside it sharing a name.
    _touch(pkg_dir / (pkg + ".py"), "def GetLevel():\n    return 7\n")
    _touch(pkg_dir / "user.py", f"import {pkg}\nLEVEL = {pkg}.GetLevel()\n")
    mods.configure(mods.build_index(tmp_path))
    _pop_after_test += [pkg, pkg + ".user", pkg + "." + pkg]

    module = importlib.import_module(pkg + ".user")

    # Without the fix this raises AttributeError: the bare import binds the
    # package (which has no GetLevel) instead of the sibling module.
    assert module.LEVEL == 7


def test_a_mod_script_finds_a_sibling_that_lives_in_the_stock_sdk(tmp_path):
    """Sibling lookup spans BOTH directories.

    A mod that replaces one module of a stock package still relies on the
    stock siblings being there, so checking only the mod's own directory
    would leave those bare imports unrewritten."""
    import tests.conftest as conftest  # the finder under test lives here

    sdk_scripts = paths.sdk_scripts()
    # ships/ is a real stock SDK package with real siblings in it.
    stock_sibling = next(p for p in sorted((sdk_scripts / "ships").glob("*.py"))
                         if p.name != "__init__.py")
    mod_file = tmp_path / "M" / "Scripts" / "ships" / "_dauntless_mod_leaf.py"
    _touch(mod_file)

    fixer = conftest._implicit_relative_fixer(
        str(mod_file), "ships/_dauntless_mod_leaf.py")

    assert fixer._pkg == "ships"
    # Both the mod's own directory and the stock package are searched.
    assert mod_file.parent in fixer._sibling_dirs
    assert sdk_scripts / "ships" in fixer._sibling_dirs
    node = ast.parse(f"import {stock_sibling.stem}").body[0]
    assert isinstance(fixer.visit_Import(node), ast.ImportFrom)


def test_a_stock_sdk_file_is_transformed_exactly_as_before(tmp_path):
    """The modless path is untouched: with no logical_rel given, the package
    still comes from the on-disk path relative to the SDK scripts root."""
    import tests.conftest as conftest

    sdk_scripts = paths.sdk_scripts()
    fixer = conftest._implicit_relative_fixer(
        str(sdk_scripts / "ships" / "Galaxy.py"), None)
    assert fixer._pkg == "ships"
    assert fixer._self_name == "Galaxy"
    assert fixer._sibling_dirs == [sdk_scripts / "ships"]

    # A file outside the SDK entirely still yields no rewrite at all.
    outside = conftest._implicit_relative_fixer(str(tmp_path / "loose.py"), None)
    assert outside._pkg is None
    assert outside.visit_Import(ast.parse("import os").body[0]).__class__ is ast.Import


# --- The bare-name fallback must honour the index --------------------------

def test_a_bare_import_does_not_defeat_a_mod_override(tmp_path, _pop_after_test):
    """The bare-name rglob branch used to load the STOCK file and register it
    as sys.modules[<qualified>], so `import Fsteamr` arriving before the first
    `import ships.Fsteamr` permanently defeated the override -- and which one
    won depended on import order."""
    import tests.conftest as conftest

    sdk_scripts = paths.sdk_scripts()
    # A real stock module reachable ONLY through the bare-name fallback: it
    # lives in a subdirectory, so the plain dotted lookup above misses it.
    leaf = "Amagon"
    stock = sdk_scripts / "ships" / (leaf + ".py")
    assert stock.exists(), "fixture assumes the stock SDK ships ships/Amagon.py"

    mod_file = tmp_path / "M" / "Scripts" / "ships" / (leaf + ".py")
    _touch(mod_file, "MARKER = 'from-the-mod'\n")
    mods.configure(mods.build_index(tmp_path))

    # Asserted on find_spec directly, so no module state is involved and the
    # test cannot be made vacuous by another test having imported this ship.
    spec = conftest._SDKFinder().find_spec(leaf, None)
    assert Path(spec.origin).resolve() == mod_file.resolve()
    assert Path(spec.origin).resolve() != stock.resolve()
    # ...and the SDK's own dotted name is bound to that SAME module, so a
    # later `import ships.Amagon` cannot pick up the stock file instead.
    assert spec.loader.also_register_as == "ships." + leaf

    if "ships." + leaf in sys.modules or leaf in sys.modules:
        return  # another test already imported this ship; the spec check stands
    _pop_after_test += [leaf, "ships." + leaf]
    module = importlib.import_module(leaf)
    assert module.MARKER == "from-the-mod"
    assert sys.modules["ships." + leaf] is module


def test_a_mod_only_module_is_reachable_by_bare_name(tmp_path, _pop_after_test):
    """A mod adding a NEW module in a subdirectory. No stock file of that name
    exists anywhere, so this cannot change stock behaviour."""
    leaf = "_dauntless_test_mod_only_leaf"
    _touch(tmp_path / "M" / "Scripts" / "Ships" / (leaf + ".py"),
           "MARKER = 'mod-only'\n")
    mods.configure(mods.build_index(tmp_path))
    _pop_after_test += [leaf, "ships." + leaf]

    module = importlib.import_module(leaf)

    assert module.MARKER == "mod-only"
    # The qualified alias uses the STOCK SDK's spelling of the directory
    # ("ships", which really exists) rather than the folded key or the mod
    # author's "Ships" -- otherwise one file would end up as two modules.
    assert sys.modules["ships." + leaf] is module


# --- A mod may not shadow the standard library -----------------------------

@pytest.mark.parametrize("name", ["types", "pickle", "string", "copyreg"])
def test_a_mod_cannot_override_a_stdlib_module(tmp_path, name):
    """_SDKFinder sits at sys.meta_path[0], ahead of BuiltinImporter and
    PathFinder, and host_loop._setup_sdk() uses this same finder in
    production. Without the gate a mod shipping Scripts/pickle.py wins for
    every stdlib import not already cached, and the breakage surfaces as an
    unrelated crash deep in engine code.

    Mods run arbitrary Python either way -- their ship scripts execute -- so
    this is not a security boundary; it buys a legible failure."""
    import tests.conftest as conftest

    _touch(tmp_path / "M" / "Scripts" / (name + ".py"),
           "raise AssertionError('the mod copy was executed')\n")
    mods.configure(mods.build_index(tmp_path))

    assert mods.sdk_override(name + ".py") is not None, "fixture must be indexed"
    assert conftest._mods_may_override(name) is False
    # No mod-provided spec is offered for it...
    assert conftest._mod_override_spec(name, name) is None
    # ...and a dotted name rooted at a stdlib package is covered too.
    assert conftest._mods_may_override(name + ".sub") is False
    # A BC name is of course still overridable.
    assert conftest._mods_may_override("loadspacehelper") is True


def test_the_gate_uses_python_3s_stdlib_names_not_python_2s():
    """`copy_reg` is Python 2's spelling and is NOT a Python 3 stdlib module,
    so the gate does not (and need not) cover it: nothing in this process
    imports `copy_reg` expecting the standard library. Recorded because the
    finding that prompted the gate named it."""
    import tests.conftest as conftest

    assert "copy_reg" not in sys.stdlib_module_names
    assert conftest._mods_may_override("copy_reg") is True
    assert conftest._mods_may_override("copyreg") is False


def test_the_stdlib_gate_leaves_the_stock_sdk_alone():
    """The SDK ships its OWN string.py and copy_reg.py. How those resolve is
    deliberately unchanged -- the gate is on MOD overrides only."""
    import tests.conftest as conftest

    sdk_scripts = paths.sdk_scripts()
    assert (sdk_scripts / "string.py").exists(), "fixture assumes SDK string.py"
    spec = conftest._SDKFinder().find_spec("string", None)
    assert spec is not None
    assert Path(spec.origin).resolve() == (sdk_scripts / "string.py").resolve()
