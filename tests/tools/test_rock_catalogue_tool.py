"""rock_catalogue CLI: determinism, layout, manifest, round-trip through the glTF files."""
import hashlib, json, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "build" / "native" / "tools" / "rock_catalogue" / "rock_catalogue"

MINI = {"tool_version": 1, "seed": 7, "bound_radius_m": 100, "impostor_view_size": 32,
        "volume_dims": 16,
        "major": {"lod_subdivisions": [3, 2], "texture_size": 64},
        "fragment": {"lod_subdivisions": [2, 1], "texture_size": 32, "cuts": [2, 4]},
        "families": [{"name": "silicate", "majors": 1, "fragments": 1,
                      "palette": [[0.4, 0.4, 0.4], [0.5, 0.5, 0.5]], "gloss": 0.12,
                      "displace": 0.35, "octaves": 5, "noise_scale": 2.3, "axis": [0.7, 1.3],
                      "craters": [2, 4], "crater_radius": [0.1, 0.25], "detail_octaves": 3,
                      "detail_scale": 7, "normal_strength": 2.5}]}

def _run(tmp, *extra):
    tmp.mkdir(parents=True, exist_ok=True)
    recipe = tmp / "recipe.json"; recipe.write_text(json.dumps(MINI))
    out = tmp / "out"
    r = subprocess.run([str(BIN), "--recipe", str(recipe), "--out", str(out), *extra],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return out

def _digest(d: Path):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}

def test_binary_exists():
    assert BIN.is_file(), f"build the tool first: {BIN}"

def test_layout_and_manifest(tmp_path):
    out = _run(tmp_path)
    man = json.loads((out / "catalogue.json").read_text())
    ids = [r["id"] for r in man["rocks"]]
    assert ids == ["majors/silicate_01", "fragments/silicate_01"]
    assert len(man["impostor_view_dirs"]) == 64
    for rock in man["rocks"]:
        for rel in rock["lods"] + [rock["volume"], rock["impostor"]["albedo"], rock["impostor"]["normal"]]:
            assert (out / rel).is_file(), rel
        g = json.loads((out / rock["lods"][0]).read_text())
        assert g["asset"]["extras"]["dauntless_volume"] == "volume.dvox"
        pos = g["accessors"][g["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
        radius = max(max(abs(v) for v in pos["max"]), max(abs(v) for v in pos["min"]))
        assert 50.0 < radius <= 100.0 + 1e-3        # axis extent <= bounding radius
    assert (out / "review" / "contact_sheet.png").is_file()

def test_deterministic(tmp_path):
    a = _digest(_run(tmp_path / "a")); b = _digest(_run(tmp_path / "b"))
    assert a == b

def test_only_writes_just_that_rock(tmp_path):
    out = _run(tmp_path, "--only", "fragments/silicate_01")
    assert (out / "fragments/silicate_01/lod0.gltf").is_file()
    assert not (out / "majors").exists()
    assert not (out / "catalogue.json").exists()

def test_bad_recipe_fails_loudly(tmp_path):
    recipe = tmp_path / "bad.json"; recipe.write_text("{}")
    r = subprocess.run([str(BIN), "--recipe", str(recipe), "--out", str(tmp_path / "o")],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "missing" in r.stderr
