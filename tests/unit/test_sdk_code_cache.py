"""The SDK loader compiles each script once per content, not once per load.

Every SDK module load re-parsed the source and re-ran the six Python 1.5
compat transforms, so each `reload()` (loadspacehelper reloads a hardpoint
on every ship spawn; the Quick Battle stats probe reloads one per ship) paid
the full transform again. Measured 2026-10-17: ~0.6 s of the Quick Battle
screen's 1.5 s first open. The compiled code is now cached per file and
reused while the file AND its sibling directories are unchanged -- the
implicit-relative-import rewrite depends on which sibling files exist, so a
sibling added or removed must recompile. Checked in BOTH twins:
tools/mission_harness.py (the production loader) and tests/conftest.py.
"""
import os
import types

import pytest

import tests.conftest as conftest
from engine import sdk_code_cache
from tools import mission_harness

TWINS = [mission_harness, conftest]


@pytest.fixture(autouse=True)
def _fresh_cache():
    sdk_code_cache.clear()
    yield
    sdk_code_cache.clear()


def _count_parses(monkeypatch, twin):
    calls = []
    real = twin._module_tree

    def spy(path, fullname):
        calls.append(path)
        return real(path, fullname)
    monkeypatch.setattr(twin, "_module_tree", spy)
    return calls


def _load(twin, path, name="cache_probe_mod", logical_rel=None):
    module = types.ModuleType(name)
    twin._SDKLoader(str(path), logical_rel=logical_rel).exec_module(module)
    return module


def _bump_mtime(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


@pytest.mark.parametrize("twin", TWINS, ids=["mission_harness", "conftest"])
def test_a_second_load_of_an_unchanged_file_does_not_reparse(tmp_path, monkeypatch, twin):
    src = tmp_path / "cache_probe_mod.py"
    src.write_text("X = 1\nL = []\n")
    calls = _count_parses(monkeypatch, twin)
    a = _load(twin, src)
    b = _load(twin, src)
    assert len(calls) == 1
    # Each load still EXECUTES: fresh module state, never shared objects.
    assert a.X == b.X == 1 and a.L is not b.L


@pytest.mark.parametrize("twin", TWINS, ids=["mission_harness", "conftest"])
def test_an_edited_file_recompiles(tmp_path, monkeypatch, twin):
    src = tmp_path / "cache_probe_mod.py"
    src.write_text("X = 1\n")
    calls = _count_parses(monkeypatch, twin)
    assert _load(twin, src).X == 1
    src.write_text("X = 2\n")             # same size: only the mtime differs
    _bump_mtime(src)
    assert _load(twin, src).X == 2
    assert len(calls) == 2


@pytest.mark.parametrize("twin", TWINS, ids=["mission_harness", "conftest"])
def test_a_sibling_file_appearing_recompiles(tmp_path, monkeypatch, twin):
    """`import b` is rewritten to `from <pkg> import b` only when b.py is a
    sibling, so the compiled code depends on the directory listing."""
    pkg = tmp_path / "QuickBattle"
    pkg.mkdir()
    src = pkg / "a.py"
    src.write_text("def f():\n    import b\n")
    calls = _count_parses(monkeypatch, twin)
    _load(twin, src, name="a", logical_rel="QuickBattle/a.py")
    (pkg / "b.py").write_text("")
    _bump_mtime(pkg)                      # the listing changed
    _load(twin, src, name="a", logical_rel="QuickBattle/a.py")
    assert len(calls) == 2
