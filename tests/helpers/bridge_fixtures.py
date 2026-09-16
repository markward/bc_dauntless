"""Fake BC install + fake mods/ tree for the ship->bridge matrix tests.

`fake_install` points engine.paths at a tmp SDK scripts dir and game data
dir (five stock ship scripts, a Hardpoints/ subdir that must NOT count as a
ship, and a real Ships.tgl); `install_mod` builds a mods/ tree and installs
it through engine.mods.build_index so the overlay path runs for real.
"""
import pytest

from engine import mods, paths
from engine import bridge_selection as bs


def write_tgl(path, strings: dict):
    from engine.missions import tgl_reader
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tgl_reader.build_tgl_bytes(strings))


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    sdk_scripts = tmp_path / "sdkroot" / "Build" / "scripts"   # paths-guard: fake install tree
    game_root = tmp_path / "gameroot"                          # paths-guard: fake install tree
    (sdk_scripts / "ships" / "Hardpoints").mkdir(parents=True)
    for stem in ("Galaxy", "Sovereign", "Akira", "BirdOfPrey", "KessokLight"):
        (sdk_scripts / "ships" / f"{stem}.py").write_text("# ship\n")
    (sdk_scripts / "ships" / "__init__.py").write_text("")
    (sdk_scripts / "ships" / "Hardpoints" / "galaxy.py").write_text("# hp\n")
    write_tgl(game_root / "data" / "TGL" / "Ships.tgl",
              {"Galaxy": "Galaxy", "Sovereign": "Sovereign", "Akira": "Akira",
               "BirdOfPrey": "Bird of Prey", "KessokLight": "Light Cruiser"})
    monkeypatch.setattr(paths, "sdk_scripts", lambda: sdk_scripts)
    monkeypatch.setattr(paths, "game_asset", lambda rel: game_root / rel)
    mods.configure(None)
    bs.clear_caches()
    yield sdk_scripts, game_root
    mods.configure(None)
    bs.clear_caches()


def install_mod(tmp_path, name, files: dict):
    root = tmp_path / "mods"
    for rel, text in files.items():
        p = root / name / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    mods.configure(mods.build_index(root))
    bs.clear_caches()
