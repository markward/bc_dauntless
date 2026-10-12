"""Per-bridge lighting document, format 3 (spec 2026-10-08-bridge-emitters §7, §13.4, §14)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld

HASH = "0123456789abcdef"


def full_doc():
    return {
        "format": ld.FORMAT,
        "source": "data/Models/Sets/DBridge/DBridge.nif",
        "materials": {
            "alcove": {
                "roughness": 0.4, "metalness": 0.0, "emission": 0.0,
                "emission_source": "texture",
                "modifiers": [
                    {"type": "state", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
                    {"type": "state", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
                    {"type": "animation", "scope": ["red"], "shape": "square",
                     "period_s": 1.0, "min": 0.2, "duty": 0.5, "soft": 0.1, "phase": 0.0},
                    {"type": "transition", "scope": ["red"], "seconds": 0.2},
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
    (lambda d: d.update(format=2), "format"),
    (lambda d: d["objects"][OBJ].update(colour=1), "colour"),
    (lambda d: d["objects"][OBJ].update(name="other"), "key"),
    (lambda d: d["objects"][OBJ].update(material="nope"), "nope"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(direction=[0, 0, 0]), "direction"),
    (lambda d: d["objects"][OBJ]["lights"][0].update(inner_deg=70), "inner_deg"),
    (lambda d: d["materials"]["alcove"].update(roughness=1.5), "roughness"),
    (lambda d: d["materials"]["alcove"].update(shine=1), "shine"),
    (lambda d: d["materials"]["alcove"].update(emission=-1), "emission"),
    (lambda d: d["materials"]["alcove"].update(emission={"strength": 1}), "emission"),
    (lambda d: d["materials"]["alcove"].update(emission_source="glow"), "emission_source"),
    (lambda d: d["materials"]["alcove"].update(fade_s=0.5), "fade_s"),
    (lambda d: _mod(d, 0).update(type="emitter"), "type"),
    (lambda d: _mod(d, 3).update(seconds=-1), "seconds"),
    (lambda d: _mod(d, 3).update(tint=[1, 1, 1]), "tint"),
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


@pytest.mark.parametrize("source", ld.EMISSION_SOURCES)
def test_every_emission_source_validates(source):
    d = full_doc()
    d["materials"]["alcove"]["emission_source"] = source
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
    assert m["alcove"]["emission"] == 0          # states without a State modifier stay dark
    assert m["alcove"]["modifiers"] == [
        {"type": "state", "tint": [1, 1, 1], "level": 1, "scope": ["green"]},
        {"type": "state", "tint": [1, 0.12, 0.08], "level": 0.5, "scope": ["red"]},
        {"type": "animation", "shape": "sine", "period_s": 2, "min": 0.2, "phase": 0.0,
         "scope": ["red"]}]
    assert "fade_s" not in m["alcove"]           # 0.5 is the default
    assert o["401:"]["lights"] == [{"position": [1, 2, 3], "direction": [0, 0, -1]}]
    # The v1 glow scale (2x) folds into the State levels.
    assert [(x["scope"], x["level"]) for x in m["roof"]["modifiers"]] == [
        (["green"], 2), (["yellow", "red"], 1.2)]
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
    assert res.error is None and res.doc["format"] == ld.FORMAT


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
    assert ld.validate(full_doc())["format"] == ld.FORMAT


def test_empty_doc_validates():
    assert ld.validate(ld.empty_doc("x.nif"))["objects"] == {}


def test_booleans_are_not_numbers():
    d = full_doc()
    d["materials"]["alcove"]["roughness"] = True
    with pytest.raises(ld.BridgeLightingError, match="roughness"):
        ld.validate(d)


# ── texture materials (Mark 2026-10-11: each TGA is a material) ─────────────

def _tex_mesh(i, block, name, tex):
    return {"mesh": i, "block": block, "name": name, "node_chain": [], "material": 0,
            "textures": [tex] if tex else []}


TEX_MESHES = [_tex_mesh(0, 10, "a", "Map 13.tga"), _tex_mesh(1, 11, "b", "map 13.TGA"),
              _tex_mesh(2, 12, "c", "Map 19.tga"), _tex_mesh(3, 13, "d", None)]


def test_texture_key_is_the_case_folded_file_name():
    assert ld.texture_key("Map 13.tga") == ld.texture_key("data\\Sets\\MAP 13.TGA") == "map 13.tga"
    assert ld.texture_stem("data/Sets/Map 13.tga") == "Map 13"


def test_textures_map_validates_and_must_name_a_material():
    d = ld.empty_doc("x")
    d["materials"]["Map 13"] = {"roughness": 0}
    d["textures"] = {"map 13.tga": "Map 13"}
    assert ld.validate(d)["textures"] == {"map 13.tga": "Map 13"}
    d["textures"] = {"map 13.tga": "ghost"}
    with pytest.raises(ld.BridgeLightingError, match="ghost"):
        ld.validate(d)
    d["textures"] = ["map 13.tga"]
    with pytest.raises(ld.BridgeLightingError, match="textures"):
        ld.validate(d)


def test_resolve_uses_the_link_else_the_texture_material():
    d = ld.empty_doc("x")
    d["materials"] = {"Map 13": {"roughness": 0}, "alcove": {}}
    d["textures"] = {"map 13.tga": "Map 13"}
    ld.object_entry(d, 11, "b")["material"] = "alcove"
    ld.object_entry(d, 12, "c")["lights"] = []          # an entry without a link
    matched, _ = ld.match_shapes(d, TEX_MESHES)
    assert ld.resolve(d, TEX_MESHES, matched) == {0: "Map 13", 1: "alcove"}


def test_resolve_ignores_a_link_whose_name_does_not_match():
    d = ld.empty_doc("x")
    d["materials"] = {"Map 13": {}, "alcove": {}}
    d["textures"] = {"map 13.tga": "Map 13"}
    ld.object_entry(d, 11, "renamed")["material"] = "alcove"
    matched, _ = ld.match_shapes(d, TEX_MESHES)
    assert ld.resolve(d, TEX_MESHES, matched)[1] == "Map 13"


def _fold_doc():
    d = ld.empty_doc("x")
    d["materials"] = {"material 1": {"roughness": 0}, "material 2": {"roughness": 0},
                      "material 3": {"roughness": 0.5}, "material 4": {"metalness": 1},
                      "alcove": {"emission": 0, "modifiers": []}}
    meshes = [_tex_mesh(0, 10, "a", "Map 13.tga"), _tex_mesh(1, 11, "b", "Map 13.tga"),
              _tex_mesh(2, 12, "c", "Map 13.tga"), _tex_mesh(3, 13, "d", "Map 13.tga"),
              _tex_mesh(4, 14, "e", "Map 19.tga"), _tex_mesh(5, 15, "f", "Map 19.tga"),
              _tex_mesh(6, 16, "g", None)]
    for block, name, mat in ((10, "a", "material 1"), (11, "b", "material 2"),
                             (12, "c", "material 3"), (14, "e", "alcove"),
                             (16, "g", "material 4")):
        ld.object_entry(d, block, name)["material"] = mat
    ld.object_entry(d, 10, "a")["lights"] = [{"position": [0, 0, 0], "direction": [0, 0, -1]}]
    return d, meshes


def test_fold_makes_the_most_common_finish_the_texture_material():
    d, meshes = _fold_doc()
    report = ld.fold_into_textures(d, meshes)
    ld.validate(d)
    assert d["textures"] == {"map 13.tga": "Map 13"}
    assert d["materials"]["Map 13"] == {"roughness": 0, "texture": "map 13.tga"}
    assert "material" not in d["objects"]["10:a"]           # lights kept, link dropped
    assert d["objects"]["10:a"]["lights"]
    assert "11:b" not in d["objects"]                       # nothing left: pruned
    assert d["objects"]["12:c"]["material"] == "Map 13 2"   # the odd one out keeps a link
    assert d["materials"]["Map 13 2"] == {"roughness": 0.5, "texture": "map 13.tga"}
    assert "material 1" not in d["materials"] and "material 3" not in d["materials"]
    assert report["Map 13"] == {"folded": 2, "kept": ["12:c"], "adopted": 1}


def test_fold_leaves_profiled_links_and_textureless_objects_alone():
    d, meshes = _fold_doc()
    ld.fold_into_textures(d, meshes)
    assert d["objects"]["14:e"]["material"] == "alcove"
    assert "map 19.tga" not in d["textures"]                # no finish-only object there
    assert d["objects"]["16:g"]["material"] == "material 4"


def test_fold_breaks_a_tie_toward_the_default_finish():
    """A tie picks the finish nearest the default (roughness 1, metalness 0),
    so meshes that adopt the texture's material change least -- DBridge
    Map 19: 'cove black' 0 vs 'cove btm edge' 0.98 must not make 16 trim
    pieces glossy."""
    d, meshes = _fold_doc()
    d["objects"]["11:b"]["material"] = "material 3"         # a: 0, b: 0.5 -- one each
    del d["objects"]["12:c"]
    ld.fold_into_textures(d, meshes)
    assert d["materials"]["Map 13"] == {"roughness": 0.5, "texture": "map 13.tga"}
    assert d["objects"]["10:a"]["material"] == "Map 13 2"


def test_fold_treats_finishes_rounding_to_the_same_twentieth_as_one():
    """Slider noise (DBridge Map 9 doors at 0.53 and 0.54) is one surface:
    finishes equal when rounded to 0.05 fold together, taking the first
    one's value."""
    d, meshes = _fold_doc()
    d["materials"]["material 2"] = {"roughness": 0.02}
    d["materials"]["material 3"] = {"roughness": 0.01}
    report = ld.fold_into_textures(d, meshes)
    assert d["materials"]["Map 13"] == {"roughness": 0, "texture": "map 13.tga"}
    assert report["Map 13"]["kept"] == []


# ── a material belongs to one texture (Mark 2026-10-11) ─────────────────────

def test_a_texture_mapping_must_name_a_material_of_that_texture():
    d = ld.empty_doc("x")
    d["materials"]["Map 13"] = {"texture": "map 5.tga"}
    d["textures"] = {"map 13.tga": "Map 13"}
    with pytest.raises(ld.BridgeLightingError, match="map 13.tga"):
        ld.validate(d)
    d["materials"]["Map 13"]["texture"] = "map 13.tga"
    ld.validate(d)
    d["materials"]["Map 13"]["texture"] = 3
    with pytest.raises(ld.BridgeLightingError, match="texture"):
        ld.validate(d)


def test_resolve_honours_a_link_only_on_its_own_texture():
    d = ld.empty_doc("x")
    d["materials"] = {"Map 13": {"texture": "map 13.tga"}, "Map 19 2": {"texture": "map 19.tga"},
                      "loose": {}}
    d["textures"] = {"map 13.tga": "Map 13"}
    ld.object_entry(d, 10, "a")["material"] = "Map 19 2"    # a Map 13 mesh: wrong texture
    ld.object_entry(d, 12, "c")["material"] = "Map 19 2"    # a Map 19 mesh: fine
    ld.object_entry(d, 13, "d")["material"] = "loose"       # no texture recorded: any mesh
    matched, _ = ld.match_shapes(d, TEX_MESHES)
    assert ld.resolve(d, TEX_MESHES, matched) == {0: "Map 13", 1: "Map 13", 2: "Map 19 2",
                                                  3: "loose"}
    assert ld.link_mismatches(d, TEX_MESHES, matched) == [
        "10:a: material 'Map 19 2' is for map 19.tga, the object uses map 13.tga; ignored"]


def test_bind_textures_records_each_materials_texture_and_splits_a_spanning_one():
    d = ld.empty_doc("x")
    d["materials"] = {"roof": {"roughness": 0}, "Map 13": {}}
    d["textures"] = {"map 13.tga": "Map 13"}
    meshes = [_tex_mesh(0, 76, "", "Map 5.tga"), _tex_mesh(1, 84, "", "Map 5.tga"),
              _tex_mesh(2, 87, "", "Map 13.tga")]
    for b in (76, 84, 87):
        ld.object_entry(d, b, "")["material"] = "roof"
    splits = ld.bind_textures(d, meshes)
    ld.validate(d)
    assert d["materials"]["roof"] == {"roughness": 0, "texture": "map 5.tga"}   # most users
    assert d["objects"]["87:"]["material"] == "roof (Map 13)"
    assert d["materials"]["roof (Map 13)"] == {"roughness": 0, "texture": "map 13.tga"}
    assert d["materials"]["Map 13"] == {"texture": "map 13.tga"}
    assert splits == ["roof: Map 13 objects moved to 'roof (Map 13)'"]



# ── format 2 -> 3 (Mark 2026-10-12: Emission is a Finish level; Emitter ->
#    State; strength folded into levels; fade -> Transition) ────────────────

def _v2():
    return {"format": 2, "source": "x", "materials": {
        "alcove": {"texture": "map 19.tga", "emission": {"without_map": "flat"}, "fade_s": 0.5,
                   "modifiers": [
                       {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
                       {"type": "animation", "scope": ["red"], "shape": "sine",
                        "period_s": 2}]},
        "Map 8": {"emission": {"strength": 3, "without_map": "texture"}, "fade_s": 1.5,
                  "modifiers": [{"type": "emitter", "scope": ["green", "red"],
                                 "tint": [1, 0.5, 0.5], "level": 0.25}]},
        "plain": {"roughness": 0.2, "emission": {"strength": 4}}},
        "textures": {"map 8.tga": "Map 8"},
        "objects": {"1:a": {"block": 1, "name": "a", "material": "alcove"}}}


def test_upgrade_of_format_2_keeps_every_state_looking_the_same():
    d = ld.validate(ld.upgrade(_v2()))
    m = d["materials"]
    assert d["format"] == ld.FORMAT and d["textures"] == {"map 8.tga": "Map 8"}
    assert m["alcove"] == {"texture": "map 19.tga", "emission": 0, "emission_source": "flat",
                           "modifiers": [
                               {"type": "state", "scope": ["green"], "tint": [1, 1, 1],
                                "level": 1},
                               {"type": "animation", "scope": ["red"], "shape": "sine",
                                "period_s": 2}]}
    assert m["Map 8"]["emission"] == 0
    assert m["Map 8"]["modifiers"] == [
        {"type": "state", "scope": ["green", "red"], "tint": [1, 0.5, 0.5], "level": 0.75},
        {"type": "transition", "scope": list(ld.STATES), "seconds": 1.5}]
    # Strength without emitters glowed nothing: it is dropped, not turned on.
    assert m["plain"] == {"roughness": 0.2}


def test_load_upgrades_a_format_2_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    (tmp_path / "bridge_lighting").mkdir()
    (tmp_path / "bridge_lighting" / f"{HASH}.json").write_text(json.dumps(_v2()))
    res = ld.load(HASH, "x")
    assert res.error is None and res.doc["format"] == ld.FORMAT


# ── room light (Mark 2026-10-12: a bridge that defines its own lights is lit
#    by them; the default room light stays only for bridges with none) ──────

def test_room_light_validates_per_state():
    d = full_doc()
    d["room_light"] = {"green": 0.2, "red": 0}
    assert ld.validate(d)["room_light"] == {"green": 0.2, "red": 0}
    for bad, frag in (({"blue": 1}, "blue"), ({"green": -1}, "green"), ([0.2], "room_light")):
        d["room_light"] = bad
        with pytest.raises(ld.BridgeLightingError, match=frag):
            ld.validate(d)


def test_room_light_is_the_bridges_own_else_off_when_it_has_lights_else_default():
    d = full_doc()                                    # object 137 has a light
    assert ld.room_light(d, "green") == 0.0
    d["room_light"] = {"green": 0.2}
    assert ld.room_light(d, "green") == 0.2 and ld.room_light(d, "red") == 0.0
    e = ld.empty_doc("x")                             # no lights: None = the default
    assert ld.room_light(e, "green") is None
    e["room_light"] = {"red": 0.5}
    assert ld.room_light(e, "red") == 0.5 and ld.room_light(e, "green") is None


# ── format 4: lights with size (spec §16.1) ─────────────────────────────────

def _with_lights(lights):
    d = ld.empty_doc("x")
    ld.object_entry(d, 5, "lip")["lights"] = lights
    return d


def test_format_is_4():
    assert ld.FORMAT == 4 and ld.empty_doc("x")["format"] == 4


def test_strip_and_panel_lights_validate():
    d = _with_lights([
        {"shape": "strip", "edge": "top", "start": 0.1, "end": 0.9, "offset": 1,
         "range": 150, "intensity": 4},
        {"shape": "panel", "x": [0, 1], "y": [0.2, 0.8], "offset": 0, "range": 400,
         "intensity": 1},
        {"shape": "strip", "edge": "left"},
        {"shape": "panel"},
        {"shape": "spot", "position": [0, 0, 0], "direction": [0, 0, -1]},
        {"position": [0, 0, 0], "direction": [0, 0, -1]}])
    assert ld.validate(d) is d


@pytest.mark.parametrize("light, where", [
    ({"shape": "tube"}, "shape"),
    ({"shape": "strip"}, "edge"),
    ({"shape": "strip", "edge": "middle"}, "edge"),
    ({"shape": "strip", "edge": "top", "start": -0.1}, "start"),
    ({"shape": "strip", "edge": "top", "end": 1.5}, "end"),
    ({"shape": "strip", "edge": "top", "start": 0.8, "end": 0.2}, "start"),
    ({"shape": "strip", "edge": "top", "x": [0, 1]}, "x"),
    ({"shape": "panel", "x": [0.5]}, "x"),
    ({"shape": "panel", "x": [0.6, 0.4]}, "x"),
    ({"shape": "panel", "y": [0, 2]}, "y"),
    ({"shape": "panel", "edge": "top"}, "edge"),
    ({"shape": "panel", "range": 0}, "range"),
    ({"shape": "panel", "intensity": -1}, "intensity"),
    ({"shape": "panel", "offset": float("nan")}, "offset"),
    ({"shape": "panel", "position": [0, 0, 0]}, "position"),
])
def test_bad_area_lights_are_rejected(light, where):
    with pytest.raises(ld.BridgeLightingError, match=where):
        ld.validate(_with_lights([light]))


def test_format_3_upgrades_to_4_unchanged_but_the_number():
    v3 = _with_lights([{"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 9}])
    v3["format"] = 3
    v3["materials"]["m"] = {"emission": 0.5}
    up = ld.validate(ld.upgrade(v3))
    assert up["format"] == 4
    assert {k: v for k, v in up.items() if k != "format"} == \
        {k: v for k, v in v3.items() if k != "format"}
    assert v3["format"] == 3                       # the input is not mutated


def test_format_2_upgrades_through_3_to_4():
    v2 = {"format": 2, "source": "x", "materials": {}, "objects": {}}
    assert ld.upgrade(v2)["format"] == 4
