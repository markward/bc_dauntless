"""Both SDK-loader twins load stock modules lifted from the retail install
(spec docs/superpowers/specs/2026-11-11-no-sdk-runtime-design.md §4.2,
decisions 1, 6 and 8).

tools/mission_harness.py is the game's loader, tests/conftest.py the suite's
copy; tests/unit/test_sdk_finder_twins_stay_in_sync.py holds them together.
Import smoke tests go through the harness's setup_sdk() and the real install;
the rules that need an odd install use a fake tree and an injected manifest.

Provenance is read from ``__spec__.origin``: these loaders build a bare
ModuleSpec, which never sets ``__file__``.
"""
import ast
import hashlib
import importlib
import sys
import types
from pathlib import Path

import pytest

import tests.conftest as conftest
import tools.mission_harness as harness
from engine import mods, paths, stock_scripts
from tools import dev_sdk

TWINS = [harness, conftest]
TWIN_IDS = ["mission_harness", "conftest"]
H = "0" * 32


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _touch(p: Path, body: str = "x = 1\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def _origin(module):
    return getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None)


def _is_under(path, root) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _retail(rel: str) -> Path:
    sf = stock_scripts.find(rel)
    if sf is None or not sf.path.is_file():
        pytest.skip(f"BC assets not available: scripts/{rel}.pyc")
    return sf.path


@pytest.fixture(autouse=True)
def _clean_mods():
    mods.configure(None)
    yield
    mods.configure(None)


@pytest.fixture
def fake_stock(tmp_path):
    """Configure a fake scripts root + manifest: {rel.pyc: bytes, listed?}."""
    root = tmp_path / "scripts"

    def make(files, unlisted=()):
        manifest = {}
        for rel, data in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            manifest[rel] = [_hash(data)]
        for rel, data in dict(unlisted).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        stock_scripts.configure(manifest, root)
        return root

    yield make
    stock_scripts.configure()


@pytest.fixture
def pop_modules():
    names = []
    yield names
    for name in reversed(names):
        sys.modules.pop(name, None)


# --- the real install, through the game's loader ---------------------------

def test_stock_module_imports_from_the_lifted_pyc():
    harness.setup_sdk()
    import MissionLib
    origin = _origin(MissionLib)
    assert origin.endswith("MissionLib.pyc")
    assert _is_under(origin, paths.stock_scripts())
    # The code itself was compiled from the lifted bytecode's path.
    fn = next(v for v in vars(MissionLib).values()
              if isinstance(v, types.FunctionType)
              and v.__module__ == "MissionLib")
    assert fn.__code__.co_filename.endswith("MissionLib.pyc")


def test_no_module_comes_from_the_sdk():
    harness.setup_sdk()
    for name in ("MissionLib", "loadspacehelper", "QuickBattle.QuickBattle",
                 "AI.Preprocessors"):
        importlib.import_module(name)
    sdk = dev_sdk.sdk_root()
    from_sdk = sorted(
        name for name, mod in list(sys.modules.items())
        if isinstance(_origin(mod), str) and _is_under(_origin(mod), sdk)
        and not name.startswith("Custom.Tutorial"))
    assert from_sdk == []


def test_tutorial_fixture_loads_from_the_sdk_in_tests():
    sf = stock_scripts.find("Custom/Tutorial/Episode/M1Basic/M1Basic")
    assert sf is not None and sf.is_fixture
    module = importlib.import_module("Custom.Tutorial.Episode.M1Basic.M1Basic")
    assert _is_under(_origin(module), dev_sdk.sdk_scripts())


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_implicit_relative_import_finds_a_pyc_sibling(twin):
    path = _retail("QuickBattle/QuickBattleAI")
    fixer = twin._implicit_relative_fixer(str(path), None)
    assert fixer._pkg == "QuickBattle"
    node = fixer.visit_Import(ast.parse("import QuickBattle").body[0])
    assert isinstance(node, ast.ImportFrom) and node.module == "QuickBattle"

    harness.setup_sdk()
    module = types.ModuleType("QuickBattle.QuickBattleAI")
    twin._SDKLoader(str(path)).exec_module(module)
    assert module.QuickBattle is importlib.import_module("QuickBattle.QuickBattle")


def test_setup_sdk_refuses_a_broken_install(fake_stock):
    stock_scripts.configure({"ZZ/Missing.pyc": [H]}, None)
    with pytest.raises(stock_scripts.StockInstallError) as err:
        harness.setup_sdk()
    assert "scripts/ZZ/Missing.pyc" in str(err.value)


def test_discover_missions_reads_bytecode(fake_stock):
    real = harness.discover_missions()
    assert "Maelstrom.Episode1.E1M1.E1M1" in real
    assert "Maelstrom.Episode1.Episode1" not in real
    assert not any("__init__" in m for m in real)

    mission = _retail("Maelstrom/Episode1/E1M1/E1M1").read_bytes()
    episode = _retail("Maelstrom/Episode1/Episode1").read_bytes()
    fake_stock({"Fake/ZZMission.pyc": mission, "Fake/ZZEpisode.pyc": episode,
                "Fake/__init__.pyc": episode})
    found = harness.discover_missions()
    assert "Fake.ZZMission" in found
    assert "Fake.ZZEpisode" not in found


# --- odd installs and mods (Review Focus 2, 4, 5) --------------------------

@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_bare_import_never_finds_an_unlisted_install_file(twin, fake_stock):
    data = _retail("ships/Galaxy").read_bytes()
    root = fake_stock({"ships/__init__.pyc": data, "ships/ZZListed.pyc": data},
                      unlisted={"ships/MyShip.pyc": data,
                                "ships/MyShip.py": b"X = 1\n"})
    listed = twin._SDKFinder().find_spec("ZZListed", None)
    assert listed is not None
    assert Path(listed.origin) == root / "ships" / "ZZListed.pyc"
    assert listed.loader.also_register_as == "ships.ZZListed"

    assert twin._SDKFinder().find_spec("MyShip", None) is None
    # Under a stock folder, "nothing listed" is a hard no: None would hand
    # the folder to Python's PathFinder, which loads the stray .py.
    with pytest.raises(ModuleNotFoundError):
        twin._SDKFinder().find_spec("ships.MyShip", [str(root / "ships")])
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("MyShip")


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_mod_py_beats_stock_pyc_on_every_branch(twin, tmp_path, monkeypatch):
    # An already-imported module is deliberately reused through _AliasLoader,
    # which would hide the branch under test; earlier tests in a full run
    # import these, so take them out of sys.modules for this test only.
    for name in ("ships.Galaxy", "Galaxy", "Bridge.Characters.Felix",
                 "Characters.Felix"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    ships = _retail("ships/Galaxy").parent
    chars = _retail("Bridge/Characters/Felix").parent
    finder = twin._SDKFinder()

    # No mod: every branch finds the stock .pyc.
    assert finder.find_spec("Characters.Felix", [str(chars)]).origin.endswith(
        "Felix.pyc")
    assert finder.find_spec("Galaxy", None).origin.endswith("Galaxy.pyc")

    galaxy = _touch(tmp_path / "M" / "Scripts" / "ships" / "Galaxy.py")
    felix = _touch(tmp_path / "M" / "Scripts" / "Bridge" / "Characters" / "Felix.py")
    mods.configure(mods.build_index(tmp_path))

    dotted = finder.find_spec("ships.Galaxy", [str(ships)])
    assert Path(dotted.origin).resolve() == galaxy.resolve()

    via_path = finder.find_spec("Characters.Felix", [str(chars)])
    assert Path(via_path.origin).resolve() == felix.resolve()
    assert via_path.loader.also_register_as == "Bridge.Characters.Felix"

    bare = finder.find_spec("Galaxy", None)
    assert Path(bare.origin).resolve() == galaxy.resolve()
    assert bare.loader.also_register_as == "ships.Galaxy"


def test_custom_package_exists_without_the_sdk(tmp_path):
    saved = {k: v for k, v in sys.modules.items()
             if k == "Custom" or k.startswith("Custom.")}
    for k in saved:
        del sys.modules[k]
    stock_scripts.clear_fixture_trees()   # conftest's reset re-registers
    try:
        _touch(tmp_path / "M" / "Scripts" / "Custom" / "Foo.py",
               "MARKER = 'foo'\n")
        mods.configure(mods.build_index(tmp_path))
        harness.setup_sdk()

        custom = importlib.import_module("Custom")
        assert _origin(custom) is None
        assert list(custom.__path__) == []
        assert [n for n in vars(custom) if not n.startswith("__")] == []

        foo = importlib.import_module("Custom.Foo")
        assert foo.MARKER == "foo"

        nano = importlib.import_module("Custom.NanoFXv2")
        fx_api = Path(paths.PROJECT_ROOT) / "engine" / "compat" / "fx_api"
        assert _is_under(_origin(nano), fx_api)
    finally:
        for k in [k for k in sys.modules
                  if k == "Custom" or k.startswith("Custom.")]:
            del sys.modules[k]
        sys.modules.update(saved)


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_an_unlisted_install_file_is_not_a_sibling(twin, fake_stock):
    data = _retail("ships/Galaxy").read_bytes()
    root = fake_stock({"Pkg/__init__.pyc": data, "Pkg/A.pyc": data,
                       "Pkg/B.pyc": data},
                      unlisted={"Pkg/Stray.pyc": data, "Pkg/Loose.py": b""})
    fixer = twin._implicit_relative_fixer(str(root / "Pkg" / "A.pyc"), None)
    assert fixer._pkg == "Pkg"
    listed = fixer.visit_Import(ast.parse("import B").body[0])
    assert isinstance(listed, ast.ImportFrom) and listed.module == "Pkg"
    for stray in ("Stray", "Loose"):
        node = fixer.visit_Import(ast.parse(f"import {stray}").body[0])
        assert isinstance(node, ast.Import)


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_a_mod_pyc_sibling_counts(twin, tmp_path):
    user = _touch(tmp_path / "M" / "Scripts" / "QuickBattle" / "ZZUser.py")
    (user.parent / "ZZModSib.pyc").write_bytes(b"")
    fixer = twin._implicit_relative_fixer(str(user), "QuickBattle/ZZUser.py")
    node = fixer.visit_Import(ast.parse("import ZZModSib").body[0])
    assert isinstance(node, ast.ImportFrom) and node.module == "QuickBattle"
    # ...and a stock sibling of the mod file's package still counts.
    stock = fixer.visit_Import(ast.parse("import QuickBattleGame").body[0])
    assert isinstance(stock, ast.ImportFrom)


# --- a stock package's __path__ never reaches the disk (decision 6) --------

@pytest.fixture
def twin_first():
    """Put one twin's finder at sys.meta_path[0], so an import through
    importlib resolves through THAT twin before anything else; and drop
    every ZZPkg module the test made."""
    saved = list(sys.meta_path)

    def install(twin):
        sys.meta_path.insert(0, twin._SDKFinder())

    yield install
    sys.meta_path[:] = saved
    for name in [n for n in sys.modules if n == "ZZPkg" or n.startswith("ZZPkg.")]:
        del sys.modules[name]


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_a_stray_file_in_a_stock_package_does_not_import(twin, fake_stock,
                                                          twin_first):
    """A stock package's __path__ points into the install. With nothing
    listed or modded for a name, Python's own PathFinder must not get to
    search that folder: it would load a stray .py as plain Python 3."""
    data = _retail("ships").read_bytes()
    fake_stock({"ZZPkg/__init__.pyc": data, "ZZPkg/Listed.pyc": data},
               unlisted={"ZZPkg/Stray.py": b"X = 1\n",
                         "ZZPkg/Loose.pyc": data})
    twin_first(twin)
    for stray in ("ZZPkg.Stray", "ZZPkg.Loose"):
        with pytest.raises(ModuleNotFoundError) as err:
            importlib.import_module(stray)
        assert err.value.name == stray
    assert "ZZPkg.Stray" not in sys.modules


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_a_listed_module_and_a_mod_still_import_from_a_stock_package(
        twin, fake_stock, twin_first, tmp_path):
    data = _retail("ships").read_bytes()
    root = fake_stock({"ZZPkg/__init__.pyc": data, "ZZPkg/Listed.pyc": data},
                      unlisted={"ZZPkg/Stray.py": b"X = 1\n"})
    mod = _touch(tmp_path / "modroot" / "M" / "Scripts" / "ZZPkg" / "ModOne.py",
                 "MARKER = 'mod'\n")
    mods.configure(mods.build_index(tmp_path / "modroot"))
    twin_first(twin)

    listed = importlib.import_module("ZZPkg.Listed")
    assert Path(_origin(listed)) == root / "ZZPkg" / "Listed.pyc"
    modded = importlib.import_module("ZZPkg.ModOne")
    assert modded.MARKER == "mod"
    assert Path(_origin(modded)).resolve() == mod.resolve()


@pytest.mark.parametrize("twin", TWINS, ids=TWIN_IDS)
def test_the_path_branch_reads_the_stock_root_at_use(twin, fake_stock):
    """An import through a package __path__ that aliases a stock folder
    (Characters -> Bridge/Characters) finds the listed file under the
    CURRENT stock root, not one captured when the loader was imported."""
    data = _retail("ships").read_bytes()
    root = fake_stock({"ZZPkg/__init__.pyc": data, "ZZPkg/Listed.pyc": data})
    spec = twin._SDKFinder().find_spec("ZZAlias.Listed", [str(root / "ZZPkg")])
    assert spec is not None
    assert Path(spec.origin) == root / "ZZPkg" / "Listed.pyc"
    assert spec.loader.also_register_as == "ZZPkg.Listed"
