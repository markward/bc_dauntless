"""A mod `.pyc` with no `.py` resolves and loads through BOTH SDK finders.

tests/conftest.py owns the finder the suite imports through and
tools/mission_harness.py the one the game uses; every case here runs against
each, because a rule that holds in only one is green tests, wrong game.

Fixtures are hand-assembled Python 1.5 bytecode (tests/helpers/
py15_assembler) in a temporary mods tree -- no BC or mod content.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §4.3-4.4.
"""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

import tools.mission_harness as harness
from engine import mods, py15
from tests.helpers import py15_assembler as A

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]
JUMPY = A.module([("JUMP_FORWARD", 0)] + RET)


def _conftest_module():
    """The already-imported tests/conftest.py (never re-import it)."""
    target = str(PROJECT_ROOT / "tests" / "conftest.py")
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) == target:
            return mod
    raise AssertionError("tests/conftest.py is not in sys.modules")


_FINDERS = {
    "conftest": lambda: _conftest_module()._SDKFinder(),
    "mission_harness": lambda: harness._SDKFinder(),
}


@pytest.fixture(params=sorted(_FINDERS))
def finder(request):
    return _FINDERS[request.param]()


@pytest.fixture(autouse=True)
def _isolated():
    mods.configure(None)
    py15._reported.clear()
    yield
    mods.configure(None)
    py15._reported.clear()


def _mod_file(root: Path, mod: str, rel: str, data) -> Path:
    path = root / mod / "Scripts" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data)
    return path


def _index(root: Path) -> None:
    mods.configure(mods.build_index(root))


def _load(finder, name):
    """find_spec + exec, without registering anything in sys.modules."""
    spec = finder.find_spec(name, None)
    assert spec is not None, name
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return spec, module


def test_a_pyc_only_mod_module_loads(finder, tmp_path, capsys):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessPycOnly.pyc",
              A.pyc(A.projectile_module(750.0)))
    _index(tmp_path)
    spec, module = _load(finder, "Tactical.Projectiles._DauntlessPycOnly")
    assert spec.origin.endswith("_DauntlessPycOnly.pyc")
    assert module.GetDamage() == 750.0
    assert "[sdk-loader]" not in capsys.readouterr().out


def test_an_upper_case_pyc_extension_loads(finder, tmp_path):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessUpper.PYC",
              A.pyc(A.projectile_module(5.0)))
    _index(tmp_path)
    _, module = _load(finder, "Tactical.Projectiles._DauntlessUpper")
    assert module.GetDamage() == 5.0


def test_a_py_beats_a_pyc_in_the_same_mod(finder, tmp_path):
    rel = "Tactical/Projectiles/_DauntlessBoth"
    _mod_file(tmp_path, "M", rel + ".pyc", A.pyc(A.projectile_module(750.0)))
    _mod_file(tmp_path, "M", rel + ".py", "def GetDamage():\n    return 1.0\n")
    _index(tmp_path)
    spec, module = _load(finder, "Tactical.Projectiles._DauntlessBoth")
    assert spec.origin.endswith(".py")
    assert module.GetDamage() == 1.0


def test_a_py_in_one_mod_beats_a_pyc_in_another(finder, tmp_path):
    rel = "Tactical/Projectiles/_DauntlessTwoMods"
    _mod_file(tmp_path, "A", rel + ".pyc", A.pyc(A.projectile_module(750.0)))
    _mod_file(tmp_path, "B", rel + ".py", "def GetDamage():\n    return 1.0\n")
    _index(tmp_path)
    spec, _ = _load(finder, "Tactical.Projectiles._DauntlessTwoMods")
    assert spec.origin.endswith(".py")


def test_a_mod_pyc_beats_the_stock_sdk_py(finder, tmp_path):
    """BC: the mod's .pyc overwrites the retail .pyc, and no stock .py
    exists to recompile from. find_spec only -- the stock module is not
    executed or replaced."""
    hit = _mod_file(tmp_path, "M", "Tactical/Projectiles/PhotonTorpedo.pyc",
                    A.pyc(A.projectile_module()))
    _index(tmp_path)
    spec = finder.find_spec("Tactical.Projectiles.PhotonTorpedo", None)
    assert spec.origin == str(hit)


def test_a_bare_name_import_finds_a_pyc_in_a_mod_subdirectory(finder, tmp_path):
    hit = _mod_file(tmp_path, "M", "Custom/_DauntlessBarePyc.pyc",
                    A.pyc(A.projectile_module()))
    _index(tmp_path)
    spec = finder.find_spec("_DauntlessBarePyc", None)
    assert spec is not None and spec.origin == str(hit)


def test_an_unloadable_pyc_fails_loudly_once(finder, tmp_path, capsys):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessJumpy.pyc",
              A.pyc(JUMPY))
    _index(tmp_path)
    for _ in range(2):
        with pytest.raises(py15.Py15Unsupported):
            _load(finder, "Tactical.Projectiles._DauntlessJumpy")
    lines = [l for l in capsys.readouterr().out.splitlines()
             if "[sdk-loader]" in l]
    assert len(lines) == 1
    assert "Tactical.Projectiles._DauntlessJumpy" in lines[0]
    assert "JUMP_FORWARD" in lines[0]


def test_an_unloadable_pyc_shadowing_stock_does_not_fall_back_to_stock(
        finder, tmp_path):
    """Spec decision D1: the mod's version was asked for; a silent stock
    substitute is not the caller's choice to make."""
    hit = _mod_file(tmp_path, "M", "Tactical/Projectiles/PhotonTorpedo.pyc",
                    A.pyc(JUMPY))
    _index(tmp_path)
    spec = finder.find_spec("Tactical.Projectiles.PhotonTorpedo", None)
    assert spec.origin == str(hit)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(py15.Py15Unsupported):
        spec.loader.exec_module(module)


def test_a_non_15_pyc_is_refused(finder, tmp_path):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessPy311.pyc",
              b"\xa7\r\r\n" + b"\x00" * 12)
    _index(tmp_path)
    with pytest.raises(py15.Py15Unsupported, match="not Python 1.5"):
        _load(finder, "Tactical.Projectiles._DauntlessPy311")


def test_reload_re_lifts_the_pyc(tmp_path):
    """SDK loadspacehelper.py calls reload(mod) on hardpoint modules; a
    .pyc-backed module must survive it. Real import machinery, so this goes
    through the suite's own (conftest) finder."""
    name = "Tactical.Projectiles._DauntlessReload"
    path = _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessReload.pyc",
                     A.pyc(A.projectile_module(1.0)))
    _index(tmp_path)
    try:
        module = importlib.import_module(name)
        assert module.GetDamage() == 1.0
        path.write_bytes(A.pyc(A.projectile_module(2.0)))
        assert importlib.reload(module).GetDamage() == 2.0
    finally:
        sys.modules.pop(name, None)


def test_a_py_in_a_later_directory_beats_a_pyc_in_an_earlier_one(finder, tmp_path):
    _mod_file(tmp_path, "M", "Custom/Aaa/_DauntlessCrossDir.pyc",
              A.pyc(A.projectile_module(750.0)))
    _mod_file(tmp_path, "M", "Custom/Bbb/_DauntlessCrossDir.py",
              "def GetDamage():\n    return 1.0\n")
    _index(tmp_path)
    spec = finder.find_spec("_DauntlessCrossDir", None)
    assert spec is not None
    assert spec.origin.endswith(".py")
