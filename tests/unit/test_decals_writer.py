"""Tests for engine/appc/decals_writer.py -- decals.json save routing and
the atomic writer (spec 2026-09-28-spv-decal-editing-design.md S2.6)."""
import json
import os
from pathlib import Path

import pytest

from engine import mods, paths
from engine.appc import decals_writer
from engine.appc import hull_decals
from engine.ui import decal_editor


NIF_REL_DIR = "data/Models/Ships/Ambassador"

AMBASSADOR_DECALS_JSON = (
    Path(__file__).resolve().parents[2]
    / "native" / "assets" / "replacements" / NIF_REL_DIR / "Masks" / "decals.json"
)


def _placement(name="top", shape=""):
    return decal_editor.Placement(
        name=name,
        origin=(1.0, 2.0, 3.0),
        u_axis=(1.0, 0.0, 0.0),
        v_axis=(0.0, 1.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        depth=2.0,
        shape=shape,
    )


@pytest.fixture(autouse=True)
def _clean():
    hull_decals.reset()
    yield
    hull_decals.reset()


# ── decals_target_path: stock routing ───────────────────────────────────

def test_decals_target_path_stock_routes_to_project_replacements(
        tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "project_asset_root", lambda: tmp_path)
    # No mod supplies this ship's model.
    monkeypatch.setattr(mods, "current",
                         lambda: mods.ModIndex(files={}, mods=[]))

    result = decals_writer.decals_target_path(NIF_REL_DIR)

    assert result == (tmp_path / "replacements" / NIF_REL_DIR
                       / "Masks" / "decals.json")


# ── decals_target_path: mod routing ─────────────────────────────────────

def test_decals_target_path_mod_routes_to_mod_folder(tmp_path, monkeypatch):
    mod_model_dir = tmp_path / "mods" / "BirdOfPreyMod" / "Data" / "Models" \
        / "Ships" / "BirdOfPrey"
    raw_rel = "data/Models/Ships/BirdOfPrey/BirdOfPrey.nif"
    mf = mods.ModFile(
        abs_path=mod_model_dir / "BirdOfPrey.nif",
        mod_name="BirdOfPreyMod",
        target="game",
        rel=mods.fold(raw_rel),
        raw_rel=raw_rel,
    )
    fake_index = mods.ModIndex(files={mf.rel: mf}, mods=[])
    monkeypatch.setattr(mods, "current", lambda: fake_index)

    result = decals_writer.decals_target_path("data/Models/Ships/BirdOfPrey")

    assert result == mod_model_dir / "Masks" / "decals.json"


# ── write_decals: atomic write ──────────────────────────────────────────

def test_write_decals_writes_atomically(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "decals.json"
    calls = []
    real_replace = os.replace

    def _spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        assert os.path.exists(src)
        real_replace(src, dst)

    monkeypatch.setattr(decals_writer.os, "replace", _spy_replace)

    decals_writer.write_decals(path, [_placement()], None)

    assert calls == [(str(path) + ".tmp", str(path))]
    assert path.is_file()
    assert not (tmp_path / "sub" / "decals.json.tmp").exists()


def test_write_decals_creates_parent_dirs(tmp_path):
    path = tmp_path / "new" / "Masks" / "decals.json"
    decals_writer.write_decals(path, [_placement()], None)
    assert path.is_file()


# ── write_decals: format and key order ──────────────────────────────────

def test_write_decals_default_registry_omitted_when_none(tmp_path):
    path = tmp_path / "decals.json"
    decals_writer.write_decals(path, [_placement()], None)

    doc = json.loads(path.read_text())
    assert "default_registry" not in doc
    assert list(doc.keys()) == ["format", "decals"]
    assert doc["format"] == 1


def test_write_decals_default_registry_included_when_set(tmp_path):
    path = tmp_path / "decals.json"
    decals_writer.write_decals(path, [_placement()], "Klingon")

    doc = json.loads(path.read_text())
    assert list(doc.keys()) == ["format", "default_registry", "decals"]
    assert doc["default_registry"] == "Klingon"


def test_write_decals_entry_matches_decal_editor_to_json_entry(tmp_path):
    path = tmp_path / "decals.json"
    p = _placement(name="bottom", shape="hull:0")
    decals_writer.write_decals(path, [p], None)

    doc = json.loads(path.read_text())
    assert doc["decals"] == {"bottom": decal_editor.to_json_entry(p)}


def test_write_decals_multiple_placements_keyed_by_name_in_order(tmp_path):
    path = tmp_path / "decals.json"
    top = _placement(name="top")
    bottom = _placement(name="bottom")
    decals_writer.write_decals(path, [top, bottom], None)

    doc = json.loads(path.read_text())
    assert list(doc["decals"].keys()) == ["top", "bottom"]


# ── write_decals: unknown top-level keys preserved ──────────────────────

def test_write_decals_preserves_unknown_top_level_keys(tmp_path):
    path = tmp_path / "decals.json"
    path.write_text(json.dumps({
        "format": 1,
        "decals": {},
        "comment": "hand-authored note",
    }))

    decals_writer.write_decals(path, [_placement()], None)

    doc = json.loads(path.read_text())
    assert doc["comment"] == "hand-authored note"
    assert doc["decals"] == {"top": decal_editor.to_json_entry(_placement())}


# ── round-trip with hull_decals' reader ─────────────────────────────────

def test_write_decals_round_trips_through_hull_decals_reader(
        tmp_path, monkeypatch):
    def _game_asset(rel):
        return tmp_path / rel
    monkeypatch.setattr(paths, "game_asset", _game_asset)

    path = tmp_path / NIF_REL_DIR / "Masks" / "decals.json"
    p = _placement(name="top", shape="amb saucer:0")
    decals_writer.write_decals(path, [p], "Zhukov")

    doc = hull_decals.load_decals_doc(NIF_REL_DIR)
    assert doc is not None
    assert doc["default_registry"] == "Zhukov"
    registry = hull_decals.resolve_registry([], doc)
    assert registry == "Zhukov"

    round_tripped = decal_editor.from_json_entry("top", doc["decals"]["top"])
    assert round_tripped == p


# ── byte-identical round-trip against the committed Ambassador file ─────

def test_write_decals_byte_identical_round_trip_of_committed_ambassador_file(
        tmp_path):
    assert AMBASSADOR_DECALS_JSON.is_file(), \
        "committed Ambassador decals.json missing -- test fixture broken"
    original_bytes = AMBASSADOR_DECALS_JSON.read_bytes()

    working = tmp_path / "decals.json"
    working.write_bytes(original_bytes)

    doc = json.loads(original_bytes.decode("utf-8"))
    placements = [decal_editor.from_json_entry(name, entry)
                  for name, entry in doc["decals"].items()]
    default_registry = doc.get("default_registry")

    decals_writer.write_decals(working, placements, default_registry)

    assert working.read_bytes() == original_bytes
