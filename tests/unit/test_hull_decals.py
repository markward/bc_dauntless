"""Tests for engine/appc/hull_decals.py -- registry mask resolution from
Masks/decals.json, and its effect on the host-loop ship model-cache key
(engine.host_loop._ship_load_key)."""
import json

import pytest
from PIL import Image

from engine import paths
from engine.appc import hull_decals


@pytest.fixture(autouse=True)
def _clean():
    hull_decals.reset()
    yield
    hull_decals.reset()


@pytest.fixture
def asset_root(tmp_path, monkeypatch):
    """Point paths.game_asset at a temp tree, mirroring the real
    <nif_rel_dir>/Masks/... layout under data/Models/Ships/Ambassador."""
    def _game_asset(rel):
        return tmp_path / rel
    monkeypatch.setattr(paths, "game_asset", _game_asset)
    return tmp_path


NIF_REL_DIR = "data/Models/Ships/Ambassador"


def _write_json(root, rel_dir, payload):
    p = root / rel_dir / "Masks" / "decals.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))
    return p


def _write_png(root, rel_dir, registry, placement, size=(2, 1)):
    p = root / rel_dir / "Masks" / registry / f"{placement}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(p)
    return p


def _valid_placement(shape="amb saucer:0"):
    return {
        "shape": shape,
        "origin": [1.0, 2.0, 3.0],
        "u_axis": [1.0, 0.0, 0.0],
        "v_axis": [0.0, 1.0, 0.0],
        "normal": [0.0, 0.0, 1.0],
        "depth": 2.0,
    }


# ── registry_stem ────────────────────────────────────────────────────────

def test_registry_stem_from_id_entry():
    reps = [("ID", "Data/Models/Ships/Ambassador/Zhukov.tga")]
    assert hull_decals.registry_stem(reps) == "Zhukov"


def test_registry_stem_last_wins():
    reps = [
        ("ID", "Data/Models/Ships/Ambassador/Zhukov.tga"),
        ("ID", "Data/Models/Ships/Ambassador/Excalibur.tga"),
    ]
    assert hull_decals.registry_stem(reps) == "Excalibur"


def test_registry_stem_none_without_id_entry():
    reps = [("PANEL", "Data/Models/Ships/Ambassador/Panel.tga")]
    assert hull_decals.registry_stem(reps) is None
    assert hull_decals.registry_stem([]) is None


# ── decals_for: happy path ──────────────────────────────────────────────

def test_decals_for_resolves_declared_placement(asset_root):
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": _valid_placement()},
    })
    mask = _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    shape, origin, u_axis, v_axis, normal, depth, mask_abs_path = specs[0]
    assert shape == "amb saucer:0"
    assert origin == (1.0, 2.0, 3.0)
    assert u_axis == (1.0, 0.0, 0.0)
    assert v_axis == (0.0, 1.0, 0.0)
    assert normal == (0.0, 0.0, 1.0)
    assert depth == 2.0
    assert mask_abs_path == str(mask)


def test_decals_for_missing_json_is_silent(asset_root, capsys):
    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")
    assert specs == []
    assert capsys.readouterr().out == ""


def test_decals_for_registry_none_is_empty_no_warning(asset_root, capsys):
    # decals.json present, but no registry resolved -- must not even try
    # to read the file.
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": _valid_placement()},
    })
    specs = hull_decals.decals_for(NIF_REL_DIR, None)
    assert specs == []
    assert capsys.readouterr().out == ""


# ── decals_for: malformed JSON / bad format ─────────────────────────────

def test_decals_for_malformed_json_warns_once(asset_root, capsys):
    p = asset_root / NIF_REL_DIR / "Masks" / "decals.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not valid json")

    specs1 = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")
    specs2 = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs1 == [] and specs2 == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_wrong_format_warns_once(asset_root, capsys):
    _write_json(asset_root, NIF_REL_DIR, {"format": 2, "decals": {}})

    specs1 = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")
    specs2 = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs1 == [] and specs2 == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


# ── decals_for: per-placement skips ─────────────────────────────────────

def test_decals_for_skips_placement_with_no_png_others_still_load(
        asset_root, capsys):
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {
            "top": _valid_placement(),      # no PNG written -> skipped
            "bottom": _valid_placement(),   # PNG written -> loads
        },
    })
    bottom_mask = _write_png(asset_root, NIF_REL_DIR, "Zhukov", "bottom")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][0] == "amb saucer:0"
    assert specs[0][6] == str(bottom_mask)
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_skips_degenerate_projector(asset_root, capsys):
    placement = _valid_placement()
    placement["v_axis"] = list(placement["u_axis"])  # parallel -> degenerate
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_skips_zero_normal(asset_root, capsys):
    # u_axis x v_axis is perfectly healthy; normal alone is degenerate. A
    # naive check that only looks at u_axis x v_axis would miss this and
    # divide-by-zero normalizing `normal` downstream.
    placement = _valid_placement()
    placement["normal"] = [0.0, 0.0, 0.0]
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


# ── decals_for: over-long JSON integers must never raise ───────────────

def test_decals_for_skips_placement_with_overlong_integer_depth(
        asset_root, capsys):
    # A JSON integer with no size limit (400 nines) parses fine via
    # json.loads, but float() of it raises OverflowError -- must be caught
    # and skip just this placement, not blow up the whole ship load.
    placement = _valid_placement()
    placement["depth"] = int("9" * 400)
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_skips_placement_with_overlong_integer_vector_component(
        asset_root, capsys):
    placement = _valid_placement()
    placement["origin"] = [int("9" * 400), 2.0, 3.0]
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_skips_inplane_normal(asset_root, capsys):
    # normal lies in span(u_axis, v_axis) (u_axis=(1,0,0), v_axis=(0,1,0),
    # normal=(1,1,0) has z=0) -- det([u v n_hat]) == 0, degenerate even
    # though u_axis x v_axis and normal are each individually non-zero.
    placement = _valid_placement()
    placement["normal"] = [1.0, 1.0, 0.0]
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


# ── _ship_load_key ───────────────────────────────────────────────────────

def test_ship_load_key_differs_by_decals():
    from engine.host_loop import _ship_load_key

    nif = "data/Models/Ships/Ambassador/Ambassador.nif"
    reps = [("ID", "/abs/Zhukov.tga")]

    zhukov_decal = ("amb saucer:0", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                     (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.0,
                     "/abs/Masks/Zhukov/top.png")
    excalibur_decal = ("amb saucer:0", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                        (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.0,
                        "/abs/Masks/Excalibur/top.png")

    key_zhukov = _ship_load_key(nif, reps, [zhukov_decal])
    key_excalibur = _ship_load_key(nif, reps, [excalibur_decal])
    key_zhukov_again = _ship_load_key(nif, reps, [zhukov_decal])
    key_no_decals = _ship_load_key(nif, reps, None)

    assert key_zhukov != key_excalibur
    assert key_zhukov == key_zhukov_again
    assert key_no_decals == _ship_load_key(nif, reps)


# ── _ship_decals: must never abort the realize loop ─────────────────────

def test_ship_decals_swallows_unexpected_exception(monkeypatch, capsys):
    # Even a fault hull_decals.decals_for itself failed to catch (a bug in
    # a future edit, or a third-party import raising inside it) must not
    # propagate out of _ship_decals and abort realize_set_objects' loop
    # over every other ship in the set.
    from engine import host_loop as hl
    from engine.appc import hull_decals as hd

    def _boom(nif_rel_dir, registry):
        raise RuntimeError("boom")

    monkeypatch.setattr(hd, "decals_for", _boom)

    nif_path = str(paths.game_root() / "data/Models/Ships/Ambassador" /
                    "Ambassador.nif")
    result = hl._ship_decals(nif_path, [("ID", "/abs/Zhukov.tga")])

    assert result == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1
    assert "RuntimeError" in out_lines[0] or "boom" in out_lines[0]
