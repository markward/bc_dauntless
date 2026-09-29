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


# ── decals_target_path: routing (Ruling L -- save where the reader reads)
#
# decals_target_path(model_rel) takes the ship's declared High model as a
# posix rel path (e.g. "data/Models/Ships/Ambassador/Ambassador.nif"), not a
# bare directory -- Task 6 doesn't exist yet, so there are no other callers
# to update.

def _mf(raw_rel, mod_name, abs_path):
    return mods.ModFile(abs_path=abs_path, mod_name=mod_name, target="game",
                         rel=mods.fold(raw_rel), raw_rel=raw_rel)


def _empty_index():
    return mods.ModIndex(files={}, mods=[])


AMBASSADOR_MODEL_REL = f"{NIF_REL_DIR}/Ambassador.nif"
BOP_DIR_REL = "data/Models/Ships/BirdOfPrey"
BOP_MODEL_REL = f"{BOP_DIR_REL}/BirdOfPrey.nif"
BOP_JSON_REL = f"{BOP_DIR_REL}/Masks/decals.json"
BOP_TEXTURE_REL = f"{BOP_DIR_REL}/High/bop_wing.tga"


def test_decals_target_path_falls_back_to_replacements_root_when_nothing_supplies_it(
        tmp_path, monkeypatch):
    # No existing decals.json anywhere, and no mod supplies the model.
    monkeypatch.setattr(mods, "replacements", _empty_index)
    monkeypatch.setattr(mods, "current", _empty_index)
    monkeypatch.setattr(mods, "replacements_root", lambda: tmp_path / "replacements")

    result = decals_writer.decals_target_path(AMBASSADOR_MODEL_REL)

    assert result == (tmp_path / "replacements" / NIF_REL_DIR
                       / "Masks" / "decals.json")


def test_decals_target_path_mod_supplying_nif_wins_over_texture_only_mod(
        tmp_path, monkeypatch):
    # Two mods touch the same directory; only one supplies the NIF itself.
    monkeypatch.setattr(mods, "replacements", _empty_index)

    nif_mod_path = tmp_path / "NifMod" / "Data" / "Models" / "Ships" \
        / "BirdOfPrey" / "BirdOfPrey.nif"
    texture_mod_path = tmp_path / "TextureMod" / "Data" / "Models" / "Ships" \
        / "BirdOfPrey" / "High" / "bop_wing.tga"
    index = mods.ModIndex(files={
        mods.fold(BOP_TEXTURE_REL): _mf(BOP_TEXTURE_REL, "TextureMod", texture_mod_path),
        mods.fold(BOP_MODEL_REL): _mf(BOP_MODEL_REL, "NifMod", nif_mod_path),
    }, mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)

    result = decals_writer.decals_target_path(BOP_MODEL_REL)

    assert result == nif_mod_path.parent / "Masks" / "decals.json"


def test_decals_target_path_texture_only_mod_does_not_capture_routing(
        tmp_path, monkeypatch):
    # Only a texture-supplying mod exists -- it must NOT be mistaken for the
    # NIF owner; routing falls through to the replacements root.
    monkeypatch.setattr(mods, "replacements", _empty_index)
    monkeypatch.setattr(mods, "replacements_root", lambda: tmp_path / "replacements")

    texture_mod_path = tmp_path / "TextureMod" / "Data" / "Models" / "Ships" \
        / "BirdOfPrey" / "High" / "bop_wing.tga"
    index = mods.ModIndex(files={
        mods.fold(BOP_TEXTURE_REL): _mf(BOP_TEXTURE_REL, "TextureMod", texture_mod_path),
    }, mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)

    result = decals_writer.decals_target_path(BOP_MODEL_REL)

    assert result == tmp_path / "replacements" / BOP_DIR_REL / "Masks" / "decals.json"


def test_decals_target_path_existing_replacements_file_wins_over_mod_supplying_nif(
        tmp_path, monkeypatch):
    # A decals.json already exists in the replacements overlay; a mod also
    # supplies the NIF. The existing replacements file must win, because
    # that's the exact file hull_decals.load_decals_doc would read.
    repl_path = tmp_path / "replacements_tree" / "decals.json"
    repl_index = mods.ModIndex(
        files={mods.fold(BOP_JSON_REL): _mf(BOP_JSON_REL, "replacements", repl_path)},
        mods=[])
    monkeypatch.setattr(mods, "replacements", lambda: repl_index)

    nif_mod_path = tmp_path / "NifMod" / "Data" / "Models" / "Ships" \
        / "BirdOfPrey" / "BirdOfPrey.nif"
    index = mods.ModIndex(
        files={mods.fold(BOP_MODEL_REL): _mf(BOP_MODEL_REL, "NifMod", nif_mod_path)},
        mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)

    result = decals_writer.decals_target_path(BOP_MODEL_REL)

    assert result == repl_path


def test_decals_target_path_existing_mod_decals_json_written_in_place(
        tmp_path, monkeypatch):
    # No replacements file, but a mod already carries its own decals.json --
    # that exact file must be the target, even though nothing there supplies
    # the NIF itself (an artist-only mod editing masks post-hoc).
    monkeypatch.setattr(mods, "replacements", _empty_index)

    existing_path = tmp_path / "SomeMod" / "Data" / "Models" / "Ships" \
        / "BirdOfPrey" / "Masks" / "decals.json"
    index = mods.ModIndex(
        files={mods.fold(BOP_JSON_REL): _mf(BOP_JSON_REL, "SomeMod", existing_path)},
        mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)

    result = decals_writer.decals_target_path(BOP_MODEL_REL)

    assert result == existing_path


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


def test_write_decals_cleans_up_tmp_file_if_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "decals.json"

    def _boom(src, dst):
        raise OSError("boom")

    monkeypatch.setattr(decals_writer.os, "replace", _boom)

    with pytest.raises(OSError):
        decals_writer.write_decals(path, [_placement()], None)

    assert not (tmp_path / "decals.json.tmp").exists()
    assert not path.exists()


# ── write_decals: refuses to overwrite a corrupt existing file (Ruling M) ─

def test_write_decals_raises_on_unparseable_existing_file(tmp_path):
    path = tmp_path / "decals.json"
    path.write_text("{ not valid json")
    original_bytes = path.read_bytes()

    with pytest.raises(ValueError) as exc_info:
        decals_writer.write_decals(path, [_placement()], None)

    assert str(path) in str(exc_info.value)
    assert path.read_bytes() == original_bytes


def test_write_decals_raises_when_existing_file_is_not_a_json_object(tmp_path):
    path = tmp_path / "decals.json"
    path.write_text(json.dumps([1, 2, 3]))
    original_bytes = path.read_bytes()

    with pytest.raises(ValueError) as exc_info:
        decals_writer.write_decals(path, [_placement()], None)

    assert str(path) in str(exc_info.value)
    assert path.read_bytes() == original_bytes


def test_write_decals_missing_existing_file_is_still_fine(tmp_path):
    path = tmp_path / "does_not_exist_yet" / "decals.json"
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


# ── write_decals: passthrough of placements the SPV could not parse ─────

_MALFORMED = {"origin": [1.0, 2.0], "u_axis": "sideways", "note": [1, {"a": None}]}


def test_write_decals_writes_passthrough_entries_after_the_placements(tmp_path):
    path = tmp_path / "decals.json"
    decals_writer.write_decals(path, [_placement("top")], None,
                               passthrough={"broken": _MALFORMED, "odd": 7})
    doc = json.loads(path.read_text())
    assert list(doc["decals"]) == ["top", "broken", "odd"]
    assert doc["decals"]["broken"] == _MALFORMED
    assert doc["decals"]["odd"] == 7


def test_write_decals_passthrough_none_or_empty_changes_nothing(tmp_path):
    a, b, c = (tmp_path / n for n in ("a.json", "b.json", "c.json"))
    decals_writer.write_decals(a, [_placement("top")], "Zhukov")
    decals_writer.write_decals(b, [_placement("top")], "Zhukov", passthrough=None)
    decals_writer.write_decals(c, [_placement("top")], "Zhukov", passthrough={})
    assert a.read_bytes() == b.read_bytes() == c.read_bytes()


def test_write_decals_refuses_a_passthrough_name_clash(tmp_path):
    """Never destroy data silently: a parsed placement and an unreadable one
    with the same name cannot both be written, so neither is."""
    path = tmp_path / "decals.json"
    path.write_text('{"format": 1, "decals": {}}')
    with pytest.raises(ValueError):
        decals_writer.write_decals(path, [_placement("top")], None,
                                   passthrough={"top": _MALFORMED})
    assert path.read_text() == '{"format": 1, "decals": {}}'


def test_save_decals_forwards_passthrough(tmp_path, monkeypatch):
    root = tmp_path / "replacements"
    monkeypatch.setattr(mods, "replacements_root", lambda: root)
    monkeypatch.setattr(mods, "current", _empty_index)
    mods.invalidate_replacements()
    written = decals_writer.save_decals(BOP_MODEL_REL, [_placement("top")], None,
                                        passthrough={"broken": _MALFORMED})
    assert json.loads(written.read_text())["decals"]["broken"] == _MALFORMED
    mods.invalidate_replacements()


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


# ── Ruling N: a FIRST save for a class must be visible to the reader ───────
#
# mods.replacements() / mods.current() are cached indexes, so a decals.json
# that did not exist when they were built is invisible to
# hull_decals.load_decals_doc (paths.game_asset) until they learn of it.

def test_invalidate_replacements_rescans_the_replacements_tree(
        tmp_path, monkeypatch):
    root = tmp_path / "replacements"
    monkeypatch.setattr(mods, "replacements_root", lambda: root)
    mods.invalidate_replacements()
    assert mods.replacements().lookup(BOP_JSON_REL) is None   # primes the cache
    (root / BOP_DIR_REL / "Masks").mkdir(parents=True)
    (root / BOP_JSON_REL).write_text("{}")
    assert mods.replacements().lookup(BOP_JSON_REL) is None   # still cached
    mods.invalidate_replacements()
    assert mods.replacements().lookup(BOP_JSON_REL).abs_path == root / BOP_JSON_REL
    mods.invalidate_replacements()


def test_first_stock_save_is_found_by_load_decals_doc(tmp_path, monkeypatch):
    root = tmp_path / "replacements"
    monkeypatch.setattr(mods, "replacements_root", lambda: root)
    monkeypatch.setattr(mods, "current", _empty_index)
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "stock")
    mods.invalidate_replacements()
    assert hull_decals.load_decals_doc(BOP_DIR_REL) is None   # primes caches

    written = decals_writer.save_decals(BOP_MODEL_REL, [_placement("top")], "IKS")

    assert written == root / BOP_JSON_REL
    doc = hull_decals.load_decals_doc(BOP_DIR_REL)
    assert doc is not None and doc["default_registry"] == "IKS"
    assert list(doc["decals"]) == ["top"]
    mods.invalidate_replacements()


def test_first_mod_routed_save_is_found_by_load_decals_doc(
        tmp_path, monkeypatch):
    monkeypatch.setattr(mods, "replacements", _empty_index)
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "stock")
    nif = tmp_path / "NifMod" / "Data" / "Models" / "Ships" / "BirdOfPrey" \
        / "BirdOfPrey.nif"
    index = mods.ModIndex(files={
        mods.fold(BOP_MODEL_REL): _mf(BOP_MODEL_REL, "NifMod", nif),
    }, mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)
    assert hull_decals.load_decals_doc(BOP_DIR_REL) is None

    written = decals_writer.save_decals(BOP_MODEL_REL, [_placement("top")], None)

    assert written == nif.parent / "Masks" / "decals.json"
    assert index.lookup(BOP_JSON_REL).mod_name == "NifMod"
    doc = hull_decals.load_decals_doc(BOP_DIR_REL)
    assert doc is not None and list(doc["decals"]) == ["top"]


def test_save_decals_failure_raises_and_leaves_the_file(tmp_path, monkeypatch):
    root = tmp_path / "replacements"
    monkeypatch.setattr(mods, "replacements_root", lambda: root)
    monkeypatch.setattr(mods, "current", _empty_index)
    target = root / BOP_JSON_REL
    target.parent.mkdir(parents=True)
    target.write_text("{not json")
    mods.invalidate_replacements()
    with pytest.raises(ValueError):
        decals_writer.save_decals(BOP_MODEL_REL, [_placement("top")], None)
    assert target.read_text() == "{not json"
    mods.invalidate_replacements()
