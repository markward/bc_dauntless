"""Tests for engine/appc/hull_decals.py -- registry mask resolution from
Masks/decals.json, and its effect on the host-loop ship model-cache key
(engine.host_loop._ship_load_key)."""
import json
import sys
import types

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


def test_ship_load_key_differs_by_decal_geometry():
    """HostController.nif_to_handle survives mission swaps, so a placement
    edited + saved in the SPV must not hand the next load the stale handle
    with the OLD placement baked in (spec S3: "on the ship's next load, the
    baked list matches")."""
    from engine.host_loop import _ship_load_key

    nif = "data/Models/Ships/Ambassador/Ambassador.nif"
    mask = "/abs/Masks/Zhukov/top.png"
    before = ("amb saucer:0", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
              (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.0, mask)
    moved = ("amb saucer:0", (0.0, 5.0, 0.0), (1.0, 0.0, 0.0),
             (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.0, mask)
    deeper = ("amb saucer:0", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
              (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.5, mask)
    unshaped = ("", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 2.0, mask)

    key = _ship_load_key(nif, [], [before])
    assert key != _ship_load_key(nif, [], [moved])
    assert key != _ship_load_key(nif, [], [deeper])
    assert key != _ship_load_key(nif, [], [unshaped])
    assert key == _ship_load_key(nif, [], [tuple(before)])
    assert key == _ship_load_key(nif, [], list([before]))
    hash(key)
    # No decals keeps the legacy bare-path key.
    assert _ship_load_key(nif, [], None) == nif
    assert _ship_load_key(nif, [], []) == nif


# ── _ship_decals: must never abort the realize loop ─────────────────────

def _fake_ship(script_name, filename_high):
    """A minimal ship stand-in: `.GetScript()` returns `script_name`, and a
    fake module registered directly in `sys.modules` under that name serves
    `GetShipStats() -> {"FilenameHigh": filename_high}` -- mirrors the real
    `ship.GetScript()` -> `importlib.import_module` -> `GetShipStats()`
    chain without touching the SDK finder or disk."""
    mod = types.ModuleType(script_name)
    mod.GetShipStats = lambda: {"FilenameHigh": filename_high}
    sys.modules[script_name] = mod
    return types.SimpleNamespace(GetScript=lambda: script_name)


@pytest.fixture
def fake_ship_module(monkeypatch):
    """Registers a fake ship script module in sys.modules for the duration
    of the test and always removes it afterwards, even if the test fails."""
    registered = []

    def _make(script_name, filename_high):
        ship = _fake_ship(script_name, filename_high)
        registered.append(script_name)
        return ship

    yield _make
    for name in registered:
        sys.modules.pop(name, None)


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
    ship = types.SimpleNamespace(
        GetScript=lambda: "ships.Ambassador")
    result = hl._ship_decals(ship, nif_path, [("ID", "/abs/Zhukov.tga")])

    assert result == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1
    assert "RuntimeError" in out_lines[0] or "boom" in out_lines[0]


# ── declared_model_dir ───────────────────────────────────────────────────

def test_declared_model_dir_from_ship_script(fake_ship_module):
    from engine.host_loop import declared_model_dir

    ship = fake_ship_module(
        "test_hull_decals.fake_ambassador",
        "data/Models/Ships/Ambassador/Ambassador.nif")

    assert declared_model_dir(ship) == "data/Models/Ships/Ambassador"


def test_declared_model_dir_none_on_script_lookup_failure():
    from engine.host_loop import declared_model_dir

    ship = types.SimpleNamespace(
        GetScript=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert declared_model_dir(ship) is None


def test_declared_model_dir_none_on_missing_filename_high(fake_ship_module):
    from engine.host_loop import declared_model_dir

    ship = fake_ship_module("test_hull_decals.fake_no_filename", "")
    # Override the fake stats to omit FilenameHigh entirely.
    sys.modules["test_hull_decals.fake_no_filename"].GetShipStats = \
        lambda: {}

    assert declared_model_dir(ship) is None


def test_declared_model_rel_is_the_posix_file_path(fake_ship_module):
    """The SPV Decals pane routes a save by the declared MODEL FILE
    (decals_target_path), not just its directory."""
    from engine.host_loop import declared_model_rel

    ship = fake_ship_module(
        "test_hull_decals.fake_ambassador_rel",
        "data\\Models\\Ships\\Ambassador\\Ambassador.nif")

    assert declared_model_rel(ship) == "data/Models/Ships/Ambassador/Ambassador.nif"


def test_declared_model_rel_none_on_script_lookup_failure():
    from engine.host_loop import declared_model_rel

    ship = types.SimpleNamespace(
        GetScript=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert declared_model_rel(ship) is None


# ── resolve_registry ─────────────────────────────────────────────────────

def test_resolve_registry_uses_script_id_stem_when_present():
    reps = [("ID", "Data/Models/Ships/Ambassador/Zhukov.tga")]
    assert hull_decals.resolve_registry(reps, {"default_registry": "Klingon"}) == "Zhukov"


def test_resolve_registry_falls_back_to_default_registry():
    assert hull_decals.resolve_registry([], {"default_registry": "Klingon"}) == "Klingon"


def test_resolve_registry_none_without_either():
    assert hull_decals.resolve_registry([], {}) is None
    assert hull_decals.resolve_registry([], None) is None
    assert hull_decals.resolve_registry(None, None) is None


# ── decals_for: default_registry, cap at 4, optional shape ─────────────

def test_decals_for_honours_default_registry(asset_root):
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "default_registry": "Klingon",
        "decals": {"top": _valid_placement()},
    })
    _write_png(asset_root, NIF_REL_DIR, "Klingon", "top")

    doc = hull_decals.load_decals_doc(NIF_REL_DIR)
    registry = hull_decals.resolve_registry([], doc)
    specs = hull_decals.decals_for(NIF_REL_DIR, registry)

    assert registry == "Klingon"
    assert len(specs) == 1
    assert specs[0][6].replace("\\", "/").endswith("Masks/Klingon/top.png")


def test_decals_for_default_registry_folder_missing_warns_once(
        asset_root, capsys):
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "default_registry": "Klingon",
        "decals": {"top": _valid_placement()},
    })
    # No Klingon/ folder written at all.

    doc = hull_decals.load_decals_doc(NIF_REL_DIR)
    registry = hull_decals.resolve_registry([], doc)
    specs = hull_decals.decals_for(NIF_REL_DIR, registry)

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_caps_at_sixteen_placements(asset_root, capsys):
    # 17 placements, all sharing ONE mask, so only the 16-placement cap
    # (never the 4-distinct-mask cap) is exercised.
    decals = {f"p{i}": _valid_placement() for i in range(17)}
    for spec in decals.values():
        spec["mask"] = "shared"
    _write_json(asset_root, NIF_REL_DIR, {"format": 1, "decals": decals})
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "shared")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 16
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_fifth_distinct_mask_is_skipped(asset_root, capsys):
    # 5 placements, each with its OWN distinct mask -> the 4-mask cap bites,
    # not the 16-placement cap.
    decals = {name: _valid_placement() for name in
              ("top", "bottom", "nacelle", "pylon", "fifth")}
    _write_json(asset_root, NIF_REL_DIR, {"format": 1, "decals": decals})
    for name in decals:
        _write_png(asset_root, NIF_REL_DIR, "Zhukov", name)

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 4
    masks = {spec[6] for spec in specs}
    assert len(masks) == 4
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_absent_mask_key_uses_placement_name(asset_root):
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": _valid_placement()},
    })
    mask = _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][6] == str(mask)


def test_decals_for_mask_key_resolves_a_shared_mask(asset_root):
    placement = _valid_placement()
    placement["mask"] = "pylon"
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"pylon_2": placement},
    })
    mask = _write_png(asset_root, NIF_REL_DIR, "Zhukov", "pylon")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][6] == str(mask)


def test_decals_for_two_placements_sharing_one_mask_both_load(asset_root):
    p1 = _valid_placement()
    p2 = _valid_placement()
    p2["mask"] = "pylon"
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"pylon": p1, "pylon_2": p2},
    })
    mask = _write_png(asset_root, NIF_REL_DIR, "Zhukov", "pylon")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 2
    assert specs[0][6] == str(mask) and specs[1][6] == str(mask)


def test_decals_for_invalid_mask_stem_is_skipped_with_warning(
        asset_root, capsys):
    bad = _valid_placement()
    bad["mask"] = "../escape"
    good = _valid_placement()
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": bad, "bottom": good},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "bottom")
    # No PNG anywhere named "../escape" or "top" -- only "bottom" resolves,
    # proving the bad "mask" key never falls back to the placement's own
    # name or is silently attempted on disk.

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


@pytest.mark.parametrize("falsy", [False, 0, 0.0, []])
def test_decals_for_falsy_non_string_mask_is_skipped_not_defaulted(
        asset_root, falsy):
    """`"mask": false` / `0` is malformed, not "absent": the editor refuses
    it (an unreadable row), so the game must skip it too, or the placement
    silently holds a mask slot the preview never counted."""
    bad = _valid_placement()
    bad["mask"] = falsy
    good = _valid_placement()
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": bad, "bottom": good},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "bottom")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][6].endswith("bottom.png")


def test_decals_for_non_string_mask_is_skipped_with_warning(
        asset_root, capsys):
    bad = _valid_placement()
    bad["mask"] = 42
    good = _valid_placement()
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": bad, "bottom": good},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "bottom")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


def test_decals_for_empty_shape_is_passed_through(asset_root):
    placement = _valid_placement(shape="")
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][0] == ""


def test_decals_for_missing_shape_key_defaults_to_empty(asset_root):
    placement = _valid_placement()
    del placement["shape"]
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert len(specs) == 1
    assert specs[0][0] == ""


def test_decals_for_non_string_shape_is_invalid(asset_root, capsys):
    placement = _valid_placement()
    placement["shape"] = 42
    _write_json(asset_root, NIF_REL_DIR, {
        "format": 1,
        "decals": {"top": placement},
    })
    _write_png(asset_root, NIF_REL_DIR, "Zhukov", "top")

    specs = hull_decals.decals_for(NIF_REL_DIR, "Zhukov")

    assert specs == []
    out_lines = [l for l in capsys.readouterr().out.splitlines() if l]
    assert len(out_lines) == 1


# ── _ship_decals: resolves beside the DECLARED model path ──────────────

def test_ship_decals_resolves_outside_game_root_via_declared_path(
        tmp_path, monkeypatch, fake_ship_module):
    """A mod-style ship whose NIF resolves outside game_root() must still
    get decals: the old `Path(nif_path).parent.relative_to(game_root())`
    computation raised ValueError for exactly this case."""
    from engine import host_loop as hl

    def _game_asset(rel):
        return tmp_path / rel
    monkeypatch.setattr(paths, "game_asset", _game_asset)

    rel_dir = "data/Models/Ships/BirdOfPrey"
    _write_json(tmp_path, rel_dir, {
        "format": 1,
        "decals": {"top": _valid_placement()},
    })
    _write_png(tmp_path, rel_dir, "Excalibur", "top")

    ship = fake_ship_module(
        "test_hull_decals.fake_bird_of_prey",
        f"{rel_dir}/BirdOfPrey.nif")

    # nif_path deliberately does NOT sit under game_root() -- it's whatever
    # a mod's own absolute install path happens to be.
    mod_nif_path = "/some/unrelated/mod/install/BirdOfPrey.nif"
    reps = [("ID", "Data/Models/Ships/BirdOfPrey/Excalibur.tga")]

    result = hl._ship_decals(ship, mod_nif_path, reps)

    assert len(result) == 1
    assert result[0][6].replace("\\", "/").endswith(
        "Masks/Excalibur/top.png")
