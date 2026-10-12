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


def test_finish_emission_and_source_clamp():
    m = {}
    ed.set_finish(m, "roughness", "1.7")
    ed.set_finish(m, "emission", "-2")
    assert m == {"roughness": 1.0, "emission": 0.0}
    ed.set_finish(m, "emission", "40")              # above the slider's 4 is fine, to a cap
    assert m["emission"] == ed.MAX_EMISSION
    ed.set_emission_source(m, "flat")
    ed.set_emission_source(m, "glow")               # refused: not a source
    assert m["emission_source"] == "flat"
    ed.clear_finish(m, "roughness")
    ed.clear_finish(m, "emission")
    assert m == {"emission_source": "flat"}


def test_modifiers_add_scope_and_fields():
    m = {}
    ed.add_modifier(m, "state", "red")
    ed.add_modifier(m, "animation", "red")
    ed.add_modifier(m, "transition", "red")
    ed.add_modifier(m, "emitter", "red")            # gone: refused
    assert m["modifiers"] == [
        {"type": "state", "scope": ["red"], "tint": [1, 1, 1], "level": 1.0},
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.0,
         "phase": 0.0},
        {"type": "transition", "scope": ["red"], "seconds": 0.5}]
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
    ed.set_modifier(m, 2, "seconds", "-1")
    assert m["modifiers"][2]["seconds"] == 0.0     # 0 = an instant cut
    ed.set_modifier(m, 2, "seconds", "99")
    assert m["modifiers"][2]["seconds"] == ed.MAX_TRANSITION_S
    ed.set_modifier(m, 2, "level", "3")            # not a Transition field: ignored
    assert "level" not in m["modifiers"][2]
    ed.remove_modifier(m, 0)
    assert len(m["modifiers"]) == 2
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


def test_room_light_set_clamp_and_clear():
    d = _doc()
    ed.set_room_light(d, "green", "0.2")
    ed.set_room_light(d, "red", "-1")
    ed.set_room_light(d, "blue", "1")               # not a state: refused
    ed.set_room_light(d, "yellow", "99")
    assert d["room_light"] == {"green": 0.2, "red": 0.0, "yellow": ed.MAX_ROOM_LIGHT}
    ld.validate(d)
    for s in ("green", "red", "yellow"):
        ed.clear_room_light(d, s)
    assert "room_light" not in d                    # pruned when empty


# ── strips and panels (spec §16.4) ──────────────────────────────────────────

def test_add_area_light_appends_a_strip_or_a_panel_with_defaults():
    d = ld.empty_doc("x")
    ed.add_area_light(d, 5, "lip", "strip")
    ed.add_area_light(d, 5, "lip", "panel")
    strip, panel = d["objects"]["5:lip"]["lights"]
    assert strip == {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0,
                     "offset": ed.STRIP_OFFSET, "range": ed.LIGHT_RANGE,
                     "intensity": ed.STRIP_INTENSITY}
    assert panel == {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0], "offset": 0.0,
                     "range": ed.LIGHT_RANGE, "intensity": ed.PANEL_INTENSITY}
    ld.validate(d)


def test_strip_fields_clamp_and_keep_start_le_end():
    light = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0}
    ed.set_light(light, "edge", "left")
    ed.set_light(light, "edge", "middle")          # ignored
    assert light["edge"] == "left"
    ed.set_light(light, "start", "0.8")
    ed.set_light(light, "end", "0.5")              # drags start down with it
    assert (light["start"], light["end"]) == (0.5, 0.5)
    ed.set_light(light, "end", "7")
    assert light["end"] == 1.0
    ed.set_light(light, "offset", "-2.5")
    assert light["offset"] == -2.5


def test_panel_span_ends_drag_each_other_and_stay_valid():
    light = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0]}
    ed.set_light(light, "x0", "0.7")
    ed.set_light(light, "x1", "0.2")
    assert light["x"] == [0.2, 0.2]
    ed.set_light(light, "y1", "-1")
    assert light["y"] == [0.0, 0.0]
    d = ld.empty_doc("x")
    ld.object_entry(d, 5, "lip")["lights"] = [light]
    ld.validate(d)


def test_set_light_drops_fields_not_valid_for_the_lights_own_shape():
    spot = {"position": [0, 0, 0], "direction": [0, 1, 0],
            "inner_deg": 30.0, "outer_deg": 60.0}
    ed.set_light(spot, "edge", "left")
    ed.set_light(spot, "start", "0.5")
    ed.set_light(spot, "x0", "0.5")
    ed.set_light(spot, "offset", "2.0")
    assert "edge" not in spot and "start" not in spot
    assert "x0" not in spot and "offset" not in spot

    strip = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0}
    ed.set_light(strip, "inner_deg", "10")
    ed.set_light(strip, "x0", "0.3")
    assert "inner_deg" not in strip and "x0" not in strip

    panel = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0]}
    ed.set_light(panel, "edge", "left")
    ed.set_light(panel, "start", "0.5")
    ed.set_light(panel, "inner_deg", "10")
    assert "edge" not in panel and "start" not in panel and "inner_deg" not in panel

    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")["lights"] = [spot]
    ld.object_entry(d, 2, "b")["lights"] = [strip]
    ld.object_entry(d, 3, "c")["lights"] = [panel]
    ld.validate(d)
