"""engine.rocks.catalogue: manifest reader, deterministic pick, stock redirect.

Spec: docs/superpowers/specs/2026-09-30-rock-catalogue-design.md
"""
import json
from pathlib import Path

import pytest

from engine import paths
from engine.rocks import catalogue as rc


def _fake_root(tmp_path, rocks):
    root = tmp_path / "rocks"
    root.mkdir()
    (root / "catalogue.json").write_text(json.dumps({
        "tool_version": 1, "recipe_fnv1a64": "0" * 16,
        "impostor_view_dirs": [[0, 1, 0]] * 16, "rocks": rocks,
    }))
    return root


def _rock(i, kind="major", family="silicate"):
    rid = f"{kind}s/{family}_{i:02d}"
    return {
        "id": rid, "kind": kind, "family": family, "lods": [f"{rid}/lod0.gltf"],
        "bound_radius_m": 100.0, "avg_albedo": [0.4, 0.4, 0.4], "gloss": 0.12,
        "impostor": {"albedo": f"{rid}/impostor_base.png", "normal": f"{rid}/impostor_normal.png",
                     "grid": 4, "view_size": 128}, "volume": f"{rid}/volume.dvox",
    }


@pytest.fixture
def fake(monkeypatch, tmp_path):
    root = _fake_root(tmp_path, [_rock(i) for i in range(1, 6)] + [_rock(1, family="icy")])
    monkeypatch.setattr(rc, "catalogue_root", lambda: root)
    # ship_model_source only redirects paths under paths.game_root() (R13);
    # the existing fixtures below use "/g/..." fake paths, so pin the root
    # to match.
    monkeypatch.setattr(paths, "game_root", lambda: Path("/g"))
    rc._memo.clear()
    return root


def test_pick_is_deterministic_and_filtered(fake):
    a = rc.pick("Unknown Debris 4")
    b = rc.pick("Unknown Debris 4")
    assert a == b and a.family == "silicate" and a.kind == "major"
    assert Path(a.lod_paths[0]).is_absolute()


def test_pick_covers_every_candidate(fake):
    seen = {rc.pick(f"Asteroid {i}").id for i in range(200)}
    assert len(seen) == 5


def test_stock_key_is_case_insensitive():
    assert rc.stock_key("/x/data/Models/Misc/Asteroids/Asteroid1.NIF") == "asteroid1.nif"
    assert rc.stock_key("/x/DATA/models/misc/asteroids/asteroid.nif") == "asteroid.nif"
    assert rc.stock_key("/x/data/Models/Ships/Galaxy/Galaxy.nif") is None
    assert rc.stock_key("/mods/foo/data/Models/Misc/Asteroids/myrock.nif") is None


def test_load_scale_hits_stock_radius(fake):
    rock = rc.pick("A")
    s = rc.load_scale(rock, "asteroid3.nif")
    assert abs(rock.bound_radius_m * rc.MODEL_UNITS_PER_METRE * s - rc.STOCK_RADIUS_MU["asteroid3.nif"]) < 1e-6


def test_ship_model_source_redirects_stock(fake):
    path, scale = rc.ship_model_source("Debris1", "/g/data/Models/Misc/Asteroids/asteroid2.NIF")
    assert path.endswith("lod0.gltf") and scale > 0 and scale != 1.0


def test_ship_model_source_leaves_others(fake):
    assert rc.ship_model_source("Galaxy", "/g/data/Models/Ships/Galaxy/Galaxy.nif") == \
        ("/g/data/Models/Ships/Galaxy/Galaxy.nif", 1.0)


def test_disabled_leaves_stock(fake):
    rc.set_enabled(False)
    p = "/g/data/Models/Misc/Asteroids/asteroid.NIF"
    assert rc.ship_model_source("A", p) == (p, 1.0)


def test_missing_catalogue_falls_back_to_stock(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "catalogue_root", lambda: tmp_path / "nope")
    monkeypatch.setattr(paths, "game_root", lambda: Path("/g"))
    rc._memo.clear()
    p = "/g/data/Models/Misc/Asteroids/asteroid.NIF"
    assert rc.ship_model_source("A", p) == (p, 1.0)
    assert rc.ship_model_source("B", p) == (p, 1.0)
    assert capsys.readouterr().err.count("rock catalogue") == 1


def test_catalogue_root_resolved_at_use(monkeypatch, tmp_path):
    from engine import paths
    monkeypatch.setattr(paths, "project_asset_root", lambda: tmp_path)
    assert rc.catalogue_root() == tmp_path / "rocks"


def test_ship_model_source_only_redirects_under_game_root(fake, monkeypatch, tmp_path):
    """R13: a stock-named asteroid NIF resolved from a MOD tree (or anywhere
    outside paths.game_root()) is left alone -- the mod author's own mesh
    wins, not the catalogue. Only a path that actually lies under the
    configured game root is a real stock BC asset eligible for redirect."""
    game_root = tmp_path / "realgame"
    mod_root = tmp_path / "mods" / "X"
    monkeypatch.setattr(paths, "game_root", lambda: game_root)

    stock_path = str(game_root / "data/Models/Misc/Asteroids/asteroid1.nif")
    mod_path = str(mod_root / "data/Models/Misc/Asteroids/asteroid1.nif")

    path, scale = rc.ship_model_source("Debris1", stock_path)
    assert path.endswith("lod0.gltf") and scale != 1.0

    assert rc.ship_model_source("Debris1", mod_path) == (mod_path, 1.0)


def test_real_catalogue_loads():
    rc._memo.clear()
    rocks = rc.load()
    assert len([r for r in rocks if r.kind == "major"]) == 13
    assert {r.family for r in rocks} == {"silicate", "carbonaceous", "icy", "metallic"}


def test_impostor_view_dirs_are_16_unit_vectors():
    rc._memo_view_dirs.clear()
    dirs = rc.impostor_view_dirs()
    assert len(dirs) == 16
    for d in dirs:
        length = sum(c * c for c in d) ** 0.5
        assert abs(length - 1.0) < 1e-3


def test_index_of_path_finds_a_real_rock_and_minus_one_for_unknown():
    rc._memo.clear()
    rocks = rc.load()
    assert rc.index_of_path(rocks[0].lod_paths[0]) == 0
    assert rc.index_of_path("/no/such/rock/lod0.gltf") == -1
