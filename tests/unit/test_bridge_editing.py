"""Pure document edits for the Bridge Editor (spec §13)."""
import pytest

from engine.bridge_editor import editing as ed, lighting_doc as ld


def _doc():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")
    ld.object_entry(d, 2, "b")
    return d


def test_new_material_links_and_names_in_order():
    d = _doc()
    assert ed.new_material(d, 1, "a") == "material 1"
    assert ed.new_material(d, 2, "b") == "material 2"
    assert d["objects"]["1:a"]["material"] == "material 1"
    assert d["materials"]["material 1"] == {}


def test_link_unlink_prunes():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    assert d["objects"]["2:b"]["material"] == "material 1"
    ed.link(d, 2, "b", "")
    assert "2:b" not in d["objects"]
    assert d["objects"]["1:a"]["material"] == "material 1"


def test_duplicate_copies_and_relinks_only_this_object():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    d["materials"]["material 1"]["roughness"] = 0.3
    assert ed.duplicate(d, 2, "b") == "material 1 copy"
    assert d["objects"]["1:a"]["material"] == "material 1"
    assert d["materials"]["material 1 copy"] == {"roughness": 0.3}
    assert ed.duplicate(d, 2, "b") == "material 1 copy copy"


def test_rename_moves_every_link_and_refuses_clashes():
    d = _doc()
    ed.new_material(d, 1, "a")
    ed.link(d, 2, "b", "material 1")
    ed.new_material(d, 3, "c")
    assert ed.rename(d, "material 1", "alcove") is None
    assert d["objects"]["1:a"]["material"] == d["objects"]["2:b"]["material"] == "alcove"
    assert "exists" in ed.rename(d, "alcove", "material 2")
    assert "empty" in ed.rename(d, "alcove", "  ")


def test_finish_surface_fade_clamp():
    m = {}
    ed.set_finish(m, "roughness", "1.7")
    ed.set_emission(m, "without_map", "flat")
    ed.set_emission(m, "without_map", "glow")     # refused: not a fallback
    ed.set_emission(m, "strength", "-2")
    ed.set_fade(m, "-1")
    assert m == {"roughness": 1.0, "emission": {"without_map": "flat", "strength": 0.0},
                 "fade_s": 0.0}
    ed.clear_finish(m, "roughness")
    assert "roughness" not in m


def test_modifiers_add_scope_and_fields():
    m = {}
    ed.add_modifier(m, "emitter", "red")
    ed.add_modifier(m, "animation", "red")
    assert m["modifiers"] == [
        {"type": "emitter", "scope": ["red"], "tint": [1, 1, 1], "level": 1.0},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0,
         "phase": 0.0}]
    ed.toggle_scope(m, 0, "green")
    ed.toggle_scope(m, 0, "red")
    assert m["modifiers"][0]["scope"] == ["green"]
    ed.set_modifier(m, 0, "tint", "0.5,0.1,0.05")
    assert m["modifiers"][0]["tint"] == pytest.approx([1.0, 0.2, 0.1])
    ed.set_modifier(m, 0, "level", "-1")
    assert m["modifiers"][0]["level"] == 0.0
    ed.set_modifier(m, 1, "shape", "square")
    assert m["modifiers"][1] == {"type": "animation", "scope": ["red"], "shape": "square",
                                 "period_s": 2.0, "min": 0.0, "phase": 0.0, "duty": 0.5,
                                 "soft": 0.0}
    ed.set_modifier(m, 1, "period_s", "0.001")
    ed.set_modifier(m, 1, "phase", "3")
    ed.set_modifier(m, 1, "shape", "sine")
    assert m["modifiers"][1] == {"type": "animation", "scope": ["red"], "shape": "sine",
                                 "period_s": 0.05, "min": 0.0, "phase": 1.0}
    ed.set_modifier(m, 1, "duty", "0.3")           # square only: ignored
    assert "duty" not in m["modifiers"][1]
    ed.remove_modifier(m, 0)
    assert len(m["modifiers"]) == 1
    d = ld.empty_doc("x")
    d["materials"]["m"] = m
    ld.validate(d)


def test_lights_add_remove_and_clamp():
    d = _doc()
    ed.add_light(d, 1, "a", (1, 2, 3), (0, 0, -1))
    ed.add_light(d, 1, "a", (4, 5, 6), (0, 0, -1))
    light = d["objects"]["1:a"]["lights"][1]
    ed.set_light(light, "inner_deg", "120")
    ed.set_light(light, "outer_deg", "10")
    assert light["inner_deg"] == 10.0 and light["outer_deg"] == 10.0
    ed.remove_light(d, 1, "a", 0)
    assert d["objects"]["1:a"]["lights"][0]["position"] == [4, 5, 6]
    ed.remove_light(d, 1, "a", 0)
    assert "1:a" not in d["objects"]


# ── texture materials (Mark 2026-10-11: each TGA is a material) ─────────────

def test_texture_material_is_made_once_and_named_after_the_texture():
    d = _doc()
    d["materials"]["Map 13"] = {}                    # a clash, e.g. a renamed link
    assert ed.texture_material(d, "data/Map 13.tga") == "Map 13 2"
    assert ed.texture_material(d, "MAP 13.TGA") == "Map 13 2"
    assert d["textures"] == {"map 13.tga": "Map 13 2"}
    assert d["materials"]["Map 13 2"] == {"texture": "map 13.tga"}


def test_rename_moves_the_texture_mapping_too():
    d = _doc()
    ed.texture_material(d, "Map 13.tga")
    assert ed.rename(d, "Map 13", "wall panels") is None
    assert d["textures"] == {"map 13.tga": "wall panels"}
    ld.validate(d)


def test_duplicate_of_an_unlinked_object_copies_its_texture_material():
    d = _doc()
    name = ed.texture_material(d, "Map 19.tga")
    d["materials"][name]["roughness"] = 0.4
    assert ed.duplicate(d, 2, "b", current=name) == "Map 19 copy"
    assert d["objects"]["2:b"]["material"] == "Map 19 copy"
    assert d["materials"]["Map 19 copy"] == {"roughness": 0.4, "texture": "map 19.tga"}
    assert d["textures"] == {"map 19.tga": "Map 19"}   # the texture keeps its own


def test_new_on_a_textured_object_makes_a_variant_of_that_texture():
    d = _doc()
    ed.texture_material(d, "Map 19.tga")
    assert ed.new_material(d, 2, "b", texture="Map 19.tga") == "Map 19 2"
    assert d["materials"]["Map 19 2"] == {"texture": "map 19.tga"}
    assert d["objects"]["2:b"]["material"] == "Map 19 2"
    assert ed.new_material(d, 1, "a", texture="Map 19.tga") == "Map 19 3"
