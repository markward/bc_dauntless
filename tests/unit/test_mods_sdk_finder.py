import importlib
import sys
from pathlib import Path

import pytest

from engine import mods


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
