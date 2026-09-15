"""Boot-time hull pre-bake: every hull the runtime could spawn gets its .dhv
baked on a worker thread at game load, so no mission ever bakes on the main
thread.

Why this exists: the bake ran at spawn (a spec §4 "first use" choice sized
from ship-only measurements), and the first E1M1 warp to Starbase 12 paid a
multi-second FedStarbase bake -- after the lattice budget stopped it from
being a 28.7-billion-cell crash. The key facts these tests pin:

  * discovery resolves the SAME (absolute hull path, authored resolution)
    pair the cache is keyed on at spawn -- host_loop._ship_nif_path's
    `paths.game_asset(FilenameHigh)` and the hardpoint's SetDamageResolution.
    Any other spelling bakes an entry nothing will ever hit;
  * the worker calls the GIL-releasing façade binding, smallest hull first,
    and one bad hull never stops the rest;
  * a ship with no resolvable hardpoint or NIF is skipped, not fatal.
"""
import threading
import types
from pathlib import Path

import pytest

from engine import mods, paths
from engine.appc import hull_volume


# ── fixtures ─────────────────────────────────────────────────────────────

def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture
def install(monkeypatch, tmp_path):
    """A fake install: two stock ship scripts, their hardpoints, their NIFs.

    Ship modules are served through the injectable importer rather than the
    SDK finder, so the test never touches sys.modules or the real SDK.
    """
    game = tmp_path / "g"
    sdk = tmp_path / "s"
    monkeypatch.setattr(paths, "game_root", lambda: game)
    monkeypatch.setattr(paths, "sdk_scripts", lambda: sdk)
    mods.configure(None)

    ships = sdk / "ships"
    _write(ships / "__init__.py", "")
    _write(ships / "Galaxy.py", "# stub\n")
    _write(ships / "Station.py", "# stub\n")
    _write(ships / "Hardpoints" / "galaxy.py",
           "Ship.SetDamageResolution(10.000000)\n")
    _write(ships / "Hardpoints" / "station.py",
           "Base.SetDamageResolution(15.000000)\n")
    # NIF sizes decide bake order: the station is the big one.
    _write(game / "data/Models/Ships/Galaxy/Galaxy.nif", "x" * 10)
    _write(game / "data/Models/Bases/Station/Station.nif", "x" * 1000)

    modules = {
        "ships.Galaxy": types.SimpleNamespace(GetShipStats=lambda: {
            "FilenameHigh": "data/Models/Ships/Galaxy/Galaxy.nif",
            "FilenameMed": "data/Models/Ships/Galaxy/GalaxyMed.nif",
            "HardpointFile": "galaxy"}),
        "ships.Station": types.SimpleNamespace(GetShipStats=lambda: {
            "FilenameHigh": "data/Models/Bases/Station/Station.nif",
            "HardpointFile": "station"}),
    }

    def fake_import(name):
        if name not in modules:
            raise ImportError(name)
        return modules[name]

    monkeypatch.setattr(hull_volume, "_import_ship_module", fake_import)
    yield types.SimpleNamespace(game=game, sdk=sdk, modules=modules)
    mods.configure(None)


class FakeRenderer:
    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def hull_volume_bake_to_disk(self, path, res):
        self.calls.append((path, res))
        if Path(path).name in self.fail_on:
            raise RuntimeError("bake exploded")
        return True


@pytest.fixture
def renderer(monkeypatch):
    r = FakeRenderer()
    monkeypatch.setattr(hull_volume, "_renderer", r)
    return r


# ── parsing ──────────────────────────────────────────────────────────────

def test_parse_damage_resolution_reads_the_authored_call():
    text = ('Ship = App.ShipProperty_Create("Ship")\n'
            'Ship.SetDamageResolution(12.000000)\n')
    assert hull_volume._parse_damage_resolution(text) == 12.0


def test_parse_damage_resolution_missing_is_none():
    assert hull_volume._parse_damage_resolution("Ship.SetMass(1.0)\n") is None


def test_parse_damage_resolution_non_positive_is_none():
    """The baker divides by this; 0 means 'never pushed' at spawn too."""
    assert hull_volume._parse_damage_resolution(
        "X.SetDamageResolution(0.000000)\n") is None


# ── discovery ────────────────────────────────────────────────────────────

def test_discovery_resolves_the_pair_the_cache_is_keyed_on(install):
    targets = hull_volume.discover_bake_targets()
    assert targets == [
        (install.game / "data/Models/Ships/Galaxy/Galaxy.nif", 10.0),
        (install.game / "data/Models/Bases/Station/Station.nif", 15.0),
    ]


def test_discovery_uses_game_asset_so_a_mod_hull_wins(install, monkeypatch):
    """The runtime loads hulls through paths.game_asset (mod overlay first).
    The cache key is that absolute path, so discovery must go through the
    same function -- not game_root()/rel -- or a modded hull bakes under the
    stock path and the spawn-time lookup misses."""
    mod_nif = install.game.parent / "mods" / "M" / "Galaxy.nif"
    _write(mod_nif, "y" * 10)
    real = paths.game_asset

    def overlay(rel):
        if rel == "data/Models/Ships/Galaxy/Galaxy.nif":
            return mod_nif
        return real(rel)

    monkeypatch.setattr(paths, "game_asset", overlay)
    targets = dict(hull_volume.discover_bake_targets())
    assert mod_nif in targets and targets[mod_nif] == 10.0


def test_discovery_skips_a_ship_whose_hardpoint_is_missing(install):
    """GenericTemplate.py declares HardpointFile "blahblah" -- a template,
    not a ship. Skipped, never fatal."""
    _write(install.sdk / "ships" / "GenericTemplate.py", "# template\n")
    install.modules["ships.GenericTemplate"] = types.SimpleNamespace(
        GetShipStats=lambda: {"FilenameHigh": "data/Models/Ships/X/X.nif",
                              "HardpointFile": "blahblah"})
    names = [p.name for p, _ in hull_volume.discover_bake_targets()]
    assert names == ["Galaxy.nif", "Station.nif"]


def test_discovery_skips_a_ship_whose_nif_is_absent(install):
    _write(install.sdk / "ships" / "Ghost.py", "# stub\n")
    _write(install.sdk / "ships" / "Hardpoints" / "ghost.py",
           "G.SetDamageResolution(8.0)\n")
    install.modules["ships.Ghost"] = types.SimpleNamespace(
        GetShipStats=lambda: {"FilenameHigh": "data/Models/Ships/Ghost/Ghost.nif",
                              "HardpointFile": "ghost"})
    names = [p.name for p, _ in hull_volume.discover_bake_targets()]
    assert names == ["Galaxy.nif", "Station.nif"]


def test_discovery_skips_a_ship_script_that_fails_to_import(install):
    _write(install.sdk / "ships" / "Broken.py", "raise RuntimeError\n")
    names = [p.name for p, _ in hull_volume.discover_bake_targets()]
    assert names == ["Galaxy.nif", "Station.nif"]


def test_discovery_includes_mod_provided_ship_scripts(install, monkeypatch):
    """A mod's ships/<name>.py (SDK overlay) is a spawnable class too."""
    modroot = install.game.parent / "mods" / "M" / "Scripts"
    _write(modroot / "ships" / "Modship.py", "# stub\n")
    _write(install.sdk / "ships" / "Hardpoints" / "modship.py",
           "M.SetDamageResolution(6.0)\n")
    _write(install.game / "data/Models/Ships/Modship/Modship.nif", "z" * 5)
    install.modules["ships.Modship"] = types.SimpleNamespace(
        GetShipStats=lambda: {"FilenameHigh": "data/Models/Ships/Modship/Modship.nif",
                              "HardpointFile": "modship"})
    mods.install(argv=["--mods-dir", str(install.game.parent / "mods")],
                 env={}, game_root=install.game, sdk_scripts=install.sdk)
    names = sorted(p.name for p, _ in hull_volume.discover_bake_targets())
    assert names == ["Galaxy.nif", "Modship.nif", "Station.nif"]


def test_discovery_reads_a_mod_overridden_hardpoint(install, monkeypatch):
    """The overlay can replace a stock hardpoint; its resolution wins."""
    modroot = install.game.parent / "mods" / "M" / "Scripts"
    _write(modroot / "ships" / "Hardpoints" / "galaxy.py",
           "Ship.SetDamageResolution(20.0)\n")
    mods.install(argv=["--mods-dir", str(install.game.parent / "mods")],
                 env={}, game_root=install.game, sdk_scripts=install.sdk)
    targets = {p.name: r for p, r in hull_volume.discover_bake_targets()}
    assert targets["Galaxy.nif"] == 20.0


# ── the worker ───────────────────────────────────────────────────────────

def test_prebake_bakes_every_target_smallest_first(install, renderer):
    t = hull_volume.prebake_all()
    assert isinstance(t, threading.Thread)
    t.join(timeout=10)
    assert not t.is_alive()
    assert renderer.calls == [
        (str(install.game / "data/Models/Ships/Galaxy/Galaxy.nif"), 10.0),
        (str(install.game / "data/Models/Bases/Station/Station.nif"), 15.0),
    ]


def test_prebake_worker_is_a_daemon(install, renderer):
    """Boot must never wait on it, and neither must exit: write_dhv's
    temp-file + rename means a mid-write exit leaves only a temp file."""
    t = hull_volume.prebake_all()
    assert t.daemon
    t.join(timeout=10)


def test_one_failing_hull_does_not_stop_the_rest(install, monkeypatch):
    r = FakeRenderer(fail_on={"Galaxy.nif"})
    monkeypatch.setattr(hull_volume, "_renderer", r)
    t = hull_volume.prebake_all()
    t.join(timeout=10)
    assert [Path(p).name for p, _ in r.calls] == ["Galaxy.nif", "Station.nif"]


def test_prebake_with_nothing_to_do_returns_none(install, renderer, monkeypatch):
    monkeypatch.setattr(hull_volume, "discover_bake_targets", lambda: [])
    assert hull_volume.prebake_all() is None
    assert renderer.calls == []


# ── real SDK (integration; only where BC content is resolvable) ──────────

def test_real_sdk_discovery_finds_the_starbase_and_the_galaxy():
    import sys
    try:
        sdk = paths.sdk_scripts()
    except Exception:  # noqa: BLE001 - no install configured here
        pytest.skip("no BC install resolvable")
    if not (sdk / "ships" / "Galaxy.py").exists():
        pytest.skip("stock ships/ not present")
    # Discovery imports every ships/*.py through the SDK finder. Leave
    # sys.modules as found: test_mods_sdk_finder asserts on which LOADER the
    # finder picks for a ship nothing else has imported, and a ship left
    # here resolves to an alias loader there instead.
    before = set(sys.modules)
    try:
        targets = {p.name: r for p, r in hull_volume.discover_bake_targets()}
        assert targets.get("Galaxy.nif") == 10.0
        assert targets.get("FedStarbase.nif") == 15.0
        for p, _ in hull_volume.discover_bake_targets():
            assert p.is_absolute() and p.is_file()
    finally:
        for name in set(sys.modules) - before:
            if name == "ships" or name.startswith("ships."):
                sys.modules.pop(name, None)


# ── boot wiring ──────────────────────────────────────────────────────────

def test_boot_starts_the_prebake(monkeypatch):
    from engine import host_loop
    started = []
    monkeypatch.setattr(hull_volume, "prebake_all", lambda: started.append(1))
    host_loop._start_hull_prebake()
    assert started == [1]


def test_boot_prebake_failure_never_propagates(monkeypatch):
    from engine import host_loop

    def boom():
        raise RuntimeError("discovery exploded")

    monkeypatch.setattr(hull_volume, "prebake_all", boom)
    host_loop._start_hull_prebake()   # must not raise


def test_run_calls_the_prebake_after_sdk_and_foundation_setup():
    """The call must sit in run() AFTER _setup_sdk() (discovery imports
    ships/*.py through the SDK finder) and after Foundation plugins load
    (they add ship scripts). Checked on the source so a refactor that drops
    or reorders the call fails here, not in a live boot."""
    import ast
    import inspect
    from engine import host_loop
    tree = ast.parse(inspect.getsource(host_loop.run))
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name in ("_setup_sdk", "load_plugins", "_start_hull_prebake"):
                order.append((node.lineno, name))
    order.sort()
    names = [n for _, n in order]
    assert "_start_hull_prebake" in names
    assert names.index("_start_hull_prebake") > names.index("_setup_sdk")
    assert names.index("_start_hull_prebake") > names.index("load_plugins")
