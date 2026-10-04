"""The committed catalogue is exactly what the tool produces from the committed recipe.

Regenerates two rocks (one major, one fragment) with --only and compares bytes. A
generator change that alters output fails here; the fix is to regenerate and commit the
catalogue deliberately (see native/assets/rocks/README.md).
"""
import json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "build" / "native" / "tools" / "rock_catalogue" / "rock_catalogue"
ROCKS = ROOT / "native" / "assets" / "rocks"
SAMPLES = ["majors/silicate_01", "fragments/icy_01"]

def _files(d): return {p.relative_to(d): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}

def test_manifest_lists_every_rock_dir():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    assert len([r for r in man["rocks"] if r["kind"] == "major"]) == 13
    assert len([r for r in man["rocks"] if r["kind"] == "fragment"]) == 24
    for r in man["rocks"]:
        assert (ROCKS / r["lods"][0]).is_file()

def test_the_mid_band_collections_are_gone():
    """The rock-fields mid band and its 48 baked collection sprites were
    removed: no recipe key, no manifest entry, no directory."""
    man = json.loads((ROCKS / "catalogue.json").read_text())
    assert "collections" not in man
    assert "collections" not in json.loads((ROCKS / "recipe.json").read_text())
    assert not (ROCKS / "collections").exists()

# rock-blend (2026-10-03): every impostor is the 8x8 (64-view) octahedral
# layout the renderer blends over, at the atlas size of the old 4x4 bake (half
# the resolution per view): 512 px.
def test_impostors_are_64_views_at_the_old_atlas_size():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    assert len(man["impostor_view_dirs"]) == 64
    for r in man["rocks"]:
        assert r["impostor"]["grid"] == 8, r["id"]
        assert r["impostor"]["grid"] * r["impostor"]["view_size"] == 512, r["id"]

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
