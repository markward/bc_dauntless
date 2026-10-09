"""Per-bridge lighting document (spec 2026-10-08-bridge-emitters §7)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld

HASH = "0123456789abcdef"


def full_doc():
    return {
        "format": 1,
        "source": "data/Models/Sets/DBridge/DBridge.nif",
        "profiles": {
            "red_bar": {
                "fade_s": 0.5,
                "green": {"tint": [1, 0.2, 0.1], "level": 0},
                "yellow": {"tint": [1, 0.6, 0.1], "level": 2,
                           "wave": {"shape": "sine", "period_s": 2.0, "min": 0.3}},
                "red": {"tint": [1, 0.1, 0.05], "level": 4,
                        "wave": {"shape": "square", "period_s": 1.0,
                                 "duty": 0.5, "soft": 0.1}},
            }
        },
        "shapes": {
            "137:wall inset slot left": {
                "block": 137, "name": "wall inset slot left",
                "material": {"roughness": 0.4, "metalness": 0.0},
                "emitter": {
                    "profile": "red_bar", "phase": 0.0,
                    "glow": {"src": "flat", "mask": "whole", "scale": 1.0},
                    "light": {"position": [191, 0, 40], "direction": [-1, 0, 0],
                              "inner_deg": 30, "outer_deg": 60, "range": 120,
                              "intensity": 1.0, "light_scale": 1.0},
                },
            }
        },
    }


def test_the_spec_example_validates():
    assert ld.validate(full_doc())["format"] == 1


def test_empty_doc_validates():
    assert ld.validate(ld.empty_doc("x.nif"))["shapes"] == {}


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d.update(format=2), "format"),
    (lambda d: d["shapes"]["137:wall inset slot left"].update(colour=1), "colour"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["material"].update(roughness=1.5), "roughness"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["material"].update(shine=1), "shine"),
    (lambda d: d["shapes"]["137:wall inset slot left"].update(name="other"), "key"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"].update(profile="nope"), "nope"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].update(mask="map"), "map"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].update(src="neon"), "src"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(direction=[0, 0, 0]), "direction"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(inner_deg=70), "inner_deg"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(range=0), "range"),
    (lambda d: d["profiles"]["red_bar"]["red"]["wave"].update(shape="saw"), "shape"),
    (lambda d: d["profiles"]["red_bar"]["yellow"]["wave"].update(duty=0.5), "duty"),
    (lambda d: d["profiles"]["red_bar"]["red"]["wave"].pop("period_s"), "period_s"),
    (lambda d: d["profiles"]["red_bar"]["green"].update(tint=[1, 1]), "tint"),
    (lambda d: d["profiles"]["red_bar"].update(blue={}), "blue"),
])
def test_invalid_documents_are_rejected_naming_the_fault(mutate, fragment):
    d = full_doc()
    mutate(d)
    with pytest.raises(ld.BridgeLightingError, match=fragment):
        ld.validate(d)


def test_booleans_are_not_numbers():
    d = full_doc()
    d["shapes"]["137:wall inset slot left"]["material"]["roughness"] = True
    with pytest.raises(ld.BridgeLightingError, match="roughness"):
        ld.validate(d)


def test_lookup_prefers_mod_dirs_then_project(tmp_path, monkeypatch):
    mod = tmp_path / "mod" / "dauntless" / "bridge_lighting"
    proj = tmp_path / "proj"
    monkeypatch.setattr(ld.paths, "game_asset_dirs",
                        lambda rel: [tmp_path / "mod" / rel, tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: proj)
    assert ld.candidate_paths(HASH) == [
        mod / f"{HASH}.json", proj / "bridge_lighting" / f"{HASH}.json"]
    assert ld.find(HASH) is None
    (proj / "bridge_lighting").mkdir(parents=True)
    (proj / "bridge_lighting" / f"{HASH}.json").write_text("{}")
    assert ld.find(HASH) == proj / "bridge_lighting" / f"{HASH}.json"
    mod.mkdir(parents=True)
    (mod / f"{HASH}.json").write_text("{}")
    assert ld.find(HASH) == mod / f"{HASH}.json"


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    (tmp_path / "bridge_lighting").mkdir()
    return tmp_path / "bridge_lighting" / f"{HASH}.json"


def test_load_without_a_file_is_an_empty_doc(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = ld.load(HASH, "x.nif")
    assert r.doc == ld.empty_doc("x.nif") and r.path is None and r.error is None


def test_load_reads_a_valid_file(tmp_path, monkeypatch):
    p = _isolate(tmp_path, monkeypatch)
    p.write_text(json.dumps(full_doc()))
    r = ld.load(HASH, "x.nif")
    assert r.error is None and r.path == p
    assert "137:wall inset slot left" in r.doc["shapes"]


@pytest.mark.parametrize("text", ["{not json", json.dumps({"format": 1, "shapes": {}, "bogus": 1})])
def test_load_reports_a_bad_file_and_keeps_its_path(tmp_path, monkeypatch, text):
    p = _isolate(tmp_path, monkeypatch)
    p.write_text(text)
    r = ld.load(HASH, "x.nif")
    assert r.error and r.path == p
    assert r.doc == ld.empty_doc("x.nif")


MESHES = [
    {"mesh": 0, "block": 137, "name": "wall inset slot left", "node_chain": [], "material": 0},
    {"mesh": 1, "block": 140, "name": "renamed", "node_chain": [], "material": 0},
]


def test_match_shapes_maps_keys_to_meshes():
    matched, warnings = ld.match_shapes(full_doc(), MESHES)
    assert matched == {"137:wall inset slot left": 0}
    assert warnings == []


def test_match_shapes_skips_a_name_mismatch():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 140, "original")["material"] = {"roughness": 0.5}
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {}
    assert len(warnings) == 1 and "140" in warnings[0] and "renamed" in warnings[0]


def test_match_shapes_warns_on_a_missing_block():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 999, "ghost")
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {} and "999" in warnings[0]


def test_shape_entry_creates_once():
    d = ld.empty_doc("x")
    e = ld.shape_entry(d, 5, "a")
    assert e == {"block": 5, "name": "a"}
    assert ld.shape_entry(d, 5, "a") is e
    ld.validate(d)
