"""Per-bridge lighting document, format 2 (spec 2026-10-08-bridge-emitters §7, §13.4)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld

HASH = "0123456789abcdef"


def full_doc():
    return {
        "format": 2,
        "source": "data/Models/Sets/DBridge/DBridge.nif",
        "materials": {
            "alcove": {
                "roughness": 0.4, "metalness": 0.0,
                "emission": {"without_map": "texture", "strength": 1.0},
                "fade_s": 0.5,
                "modifiers": [
                    {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
                    {"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                    {"type": "animation", "scope": ["red"], "shape": "square",
                     "period_s": 1.0, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0.0},
                ],
            }
        },
        "objects": {
            "137:wall inset slot left": {
                "block": 137, "name": "wall inset slot left", "material": "alcove",
                "lights": [{"position": [191, 0, 40], "direction": [-1, 0, 0],
                            "inner_deg": 30, "outer_deg": 60, "range": 120,
                            "intensity": 1.0}],
            }
        },
    }


OBJ = "137:wall inset slot left"


def _mod(d, i):
    return d["materials"]["alcove"]["modifiers"][i]


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d.update(format=3), "format"),
    (lambda d: d["objects"][OBJ].update(colour=1), "colour"),
    (lambda d: d["objects"][OBJ].update(name="other"), "key"),
    (lambda d: d["objects"][OBJ].update(material="nope"), "nope"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(direction=[0, 0, 0]), "direction"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(inner_deg=70), "inner_deg"),
    (lambda d: d["materials"]["alcove"].update(roughness=1.5), "roughness"),
    (lambda d: d["materials"]["alcove"].update(shine=1), "shine"),
    (lambda d: d["materials"]["alcove"]["emission"].update(without_map="glow"), "without_map"),
    (lambda d: d["materials"]["alcove"]["emission"].update(src="auto"), "src"),
    (lambda d: d["materials"]["alcove"]["emission"].update(strength=-1), "strength"),
    (lambda d: _mod(d, 0).update(scope=["green", "blue"]), "scope"),
    (lambda d: _mod(d, 0).update(scope=["green", "green"]), "scope"),
    (lambda d: _mod(d, 0).update(tint=[1, 1]), "tint"),
    (lambda d: _mod(d, 0).update(type="spark"), "type"),
    (lambda d: _mod(d, 2).update(shape="saw"), "shape"),
    (lambda d: _mod(d, 2).pop("period_s"), "period_s"),
    (lambda d: _mod(d, 2).update(shape="sine"), "duty"),        # duty/soft are square-only
    (lambda d: _mod(d, 2).update(phase=1.5), "phase"),
])
def test_invalid_documents_are_rejected_naming_the_fault(mutate, fragment):
    d = full_doc()
    mutate(d)
    with pytest.raises(ld.BridgeLightingError, match=fragment):
        ld.validate(d)


def test_an_empty_scope_is_a_parked_modifier():
    d = full_doc()
    _mod(d, 0)["scope"] = []
    assert ld.validate(d)


@pytest.mark.parametrize("fallback", ld.EMISSION_WITHOUT_MAP)
def test_every_emission_fallback_validates(fallback):
    d = full_doc()
    d["materials"]["alcove"]["emission"] = {"without_map": fallback}
    assert ld.validate(d)


def test_object_entry_creates_once():
    d = ld.empty_doc("x")
    e = ld.object_entry(d, 4, "lamp")
    assert ld.object_entry(d, 4, "lamp") is e
    assert d["objects"] == {"4:lamp": {"block": 4, "name": "lamp"}}


def _v1():
    return {
        "format": 1, "source": "x",
        "profiles": {
            "alcove": {"fade_s": 0.5,
                       "green": {"tint": [1, 1, 1], "level": 1},
                       "red": {"tint": [1, 0.12, 0.08], "level": 0.5,
                               "wave": {"shape": "sine", "period_s": 2, "min": 0.2}}},
            "roof": {"fade_s": 0.5,
                     "green": {"tint": [1, 1, 1], "level": 1},
                     "yellow": {"tint": [1, 1, 1], "level": 0.6},
                     "red": {"tint": [1, 1, 1], "level": 0.6}},
        },
        "shapes": {
            "401:": {"block": 401, "name": "",
                     "emitter": {"profile": "alcove", "glow": {"src": "texture"},
                                 "light": {"position": [1, 2, 3], "direction": [0, 0, -1]}}},
            "423:": {"block": 423, "name": "",
                     "emitter": {"profile": "alcove", "glow": {"src": "texture"},
                                 "light": {"position": [4, 5, 6], "direction": [0, 0, -1]}}},
            "81:": {"block": 81, "name": "",
                    "emitter": {"profile": "roof", "glow": {"src": "emissive", "scale": 2}}},
            "133:": {"block": 133, "name": "", "material": {"roughness": 0}},
            "139:": {"block": 139, "name": "", "material": {"roughness": 0}},
            "299:": {"block": 299, "name": "",
                     "emitter": {"light": {"position": [7, 8, 9], "direction": [1, 0, 0]}}},
        },
    }


def test_upgrade_of_the_real_dbridge_shape_is_lossless_where_it_matters():
    d = ld.validate(ld.upgrade(_v1()))
    m, o = d["materials"], d["objects"]
    assert o["401:"]["material"] == o["423:"]["material"] == "alcove"
    assert m["alcove"]["emission"] == {"without_map": "texture"}
    assert m["alcove"]["modifiers"] == [
        {"type": "emitter", "tint": [1, 1, 1], "level": 1, "scope": ["green"]},
        {"type": "emitter", "tint": [1, 0.12, 0.08], "level": 0.5, "scope": ["red"]},
        {"type": "animation", "shape": "sine", "period_s": 2, "min": 0.2, "phase": 0.0,
         "scope": ["red"]}]
    assert o["401:"]["lights"] == [{"position": [1, 2, 3], "direction": [0, 0, -1]}]
    assert m["roof"]["emission"] == {"without_map": "texture", "strength": 2}
    assert [x["scope"] for x in m["roof"]["modifiers"]] == [["green"], ["yellow", "red"]]
    # Finish-only objects are never merged: equal values are a coincidence,
    # not a choice to share (Mark, 2026-10-11) -- each gets its own material.
    assert (o["133:"]["material"], o["139:"]["material"]) == ("material 1", "material 2")
    assert m["material 1"] == m["material 2"] == {"roughness": 0}
    assert o["299:"] == {"block": 299, "name": "", "lights": [{"position": [7, 8, 9],
                                                               "direction": [1, 0, 0]}]}


def test_upgrade_gives_a_profile_shared_with_different_settings_its_own_material():
    v1 = _v1()
    v1["shapes"]["423:"]["emitter"]["phase"] = 0.5
    d = ld.upgrade(v1)
    assert d["objects"]["401:"]["material"] == "alcove"
    assert d["objects"]["423:"]["material"] == "alcove 2"


def test_load_upgrades_a_format_1_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    (tmp_path / "bridge_lighting").mkdir()
    (tmp_path / "bridge_lighting" / f"{HASH}.json").write_text(json.dumps(_v1()))
    res = ld.load(HASH, "x")
    assert res.error is None and res.doc["format"] == 2


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
    assert "137:wall inset slot left" in r.doc["objects"]


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
    ld.object_entry(d, 140, "original")
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {}
    assert len(warnings) == 1 and "140" in warnings[0] and "renamed" in warnings[0]


def test_match_shapes_warns_on_a_missing_block():
    d = ld.empty_doc("x")
    ld.object_entry(d, 999, "ghost")
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {} and "999" in warnings[0]


def test_the_spec_example_validates():
    assert ld.validate(full_doc())["format"] == 2


def test_empty_doc_validates():
    assert ld.validate(ld.empty_doc("x.nif"))["objects"] == {}


def test_booleans_are_not_numbers():
    d = full_doc()
    d["materials"]["alcove"]["roughness"] = True
    with pytest.raises(ld.BridgeLightingError, match="roughness"):
        ld.validate(d)
