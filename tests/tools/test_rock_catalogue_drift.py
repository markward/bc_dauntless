"""The committed catalogue is exactly what the tool produces from the committed recipe.

Regenerates two rocks (one major, one fragment) and one rock collection with --only and compares bytes. A
generator change that alters output fails here; the fix is to regenerate and commit the
catalogue deliberately (see native/assets/rocks/README.md).
"""
import json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "build" / "native" / "tools" / "rock_catalogue" / "rock_catalogue"
ROCKS = ROOT / "native" / "assets" / "rocks"
SAMPLES = ["majors/silicate_01", "fragments/icy_01", "collections/dense_00"]

def _files(d): return {p.relative_to(d): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}

def test_manifest_lists_every_rock_dir():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    assert len([r for r in man["rocks"] if r["kind"] == "major"]) == 13
    assert len([r for r in man["rocks"] if r["kind"] == "fragment"]) == 24
    for r in man["rocks"]:
        assert (ROCKS / r["lods"][0]).is_file()

def test_manifest_lists_every_collection():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    cols = man["collections"]
    assert len(cols) == 48
    assert {c["variant"] for c in cols} == {"sparse", "medium", "dense"}
    for c in cols:
        assert (ROCKS / c["impostor"]["albedo"]).is_file()
        assert (ROCKS / c["impostor"]["normal"]).is_file()

def test_samples_regenerate_byte_identical(tmp_path):
    args = [str(BIN), "--recipe", str(ROCKS / "recipe.json"), "--out", str(tmp_path)]
    for s in SAMPLES: args += ["--only", s]
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    for s in SAMPLES:
        assert _files(tmp_path / s) == _files(ROCKS / s), f"{s} drifted from the committed catalogue"

def test_manifest_recipe_hash_matches_recipe():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    # Standard FNV-1a 64 offset basis 14695981039346656037 (0xcbf29ce484222325),
    # matching rockgen::fnv1a64. (The brief's literal was missing a digit.)
    h = 14695981039346656037
    for b in (ROCKS / "recipe.json").read_bytes():
        h ^= b; h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    assert man["recipe_fnv1a64"] == f"{h:016x}"

# rock-real Part 2 (2026-10-03): a mid collection sprite must never picture a
# rock that reads as a big asteroid -- nothing real stands behind a sprite.
# The largest L0 sprite (mid_l0_tile_gu / 2 x mid_sprite_scale x 1.2, the top
# of rock_mid.cc's 0.8..1.2 size jitter) maps the collection's unit radius to
# GU; its largest part must stay within the smallest real large rock.
_L0_JITTER_MAX = 1.2   # rock_mid.cc: half = 0.5 * diameter * sprite_scale * (0.8 + 0.4 u)
# The collection atlases before Part 2: 48 collections x 2 maps x 512^2 RGBA8.
_ATLAS_BYTES_BEFORE = 48 * 2 * 512 * 512 * 4


def test_collection_parts_are_gravel_at_l0():
    from engine.rocks import far_dials
    d = far_dials.DEFAULTS
    recipe = json.loads((ROCKS / "recipe.json").read_text())
    size_max = recipe["collections"]["size"][1]
    half_gu = 0.5 * d["mid_l0_tile_gu"] * d["mid_sprite_scale"] * _L0_JITTER_MAX
    assert size_max * half_gu <= d["near_large_r_min"] + 1e-9, (size_max * half_gu)


def test_collection_atlases_cost_at_most_twice_the_original():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    total = 0
    for c in man["collections"]:
        side = c["impostor"]["grid"] * c["impostor"]["view_size"]
        total += 2 * side * side * 4   # albedo + normal, RGBA8
    assert total <= 2 * _ATLAS_BYTES_BEFORE, total / _ATLAS_BYTES_BEFORE
