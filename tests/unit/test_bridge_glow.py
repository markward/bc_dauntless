"""Objects -> per-mesh glow (spec §13.2)."""
import copy

import pytest

from engine.bridge_editor import behaviour as bh, glow, lighting_doc as ld

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]
ROOF = {"emission": {"strength": 2}, "modifiers": [
    {"type": "emitter", "scope": ["green", "red"], "tint": [0.5, 0.5, 1], "level": 0.6}]}


def _doc():
    d = ld.empty_doc("x")
    d["materials"]["roof"] = copy.deepcopy(ROOF)   # tests mutate it
    d["materials"]["finish only"] = {"roughness": 0}
    ld.object_entry(d, 10, "panel")["material"] = "roof"
    ld.object_entry(d, 11, "alcove")["material"] = "roof"
    ld.object_entry(d, 12, "wall")["material"] = "finish only"
    return d


MATCHED = {"10:panel": 3, "11:alcove": 4, "12:wall": 5}


def _links(d, matched):
    """The resolved {mesh: material} for meshes with no texture: links only."""
    return ld.resolve(d, [{"mesh": i} for i in matched.values()], matched)


def test_auto_surface_resolves_per_object():
    objs, warnings = glow.glow_objects(_doc(), _links(_doc(), MATCHED), MESHES)
    assert [(m, s, st) for m, s, _, st in objs] == [(3, 0, 2.0), (4, 1, 2.0)]
    assert warnings == []


def test_a_material_without_emitters_adds_no_glow():
    objs, _ = glow.glow_objects(_doc(), _links(_doc(), {"12:wall": 5}), MESHES)
    assert objs == []


def test_the_map_wins_and_without_a_map_the_fallback_applies():
    # Spec §13 (Mark 2026-10-11): like roughness/metalness, an object's
    # emission map is used whenever it has one; otherwise `without_map`.
    d = _doc()
    d["materials"]["roof"]["emission"]["without_map"] = "flat"
    objs, warnings = glow.glow_objects(d, _links(d, MATCHED), MESHES)
    assert [(m, s) for m, s, _, _ in objs] == [(3, 0), (4, 2)]
    assert warnings == []


def test_strength_zero_glows_nothing_but_still_owns_the_glow():
    d = _doc()
    d["materials"]["roof"]["emission"]["strength"] = 0
    objs, _ = glow.glow_objects(d, _links(d, MATCHED), MESHES)
    (_, _, rgb, k), _ = glow.live(objs, bh.StateFade("red"), 0.0)
    assert rgb == (0.0, 0.0, 0.0) and k == 0.0


def test_live_scales_by_strength():
    objs, _ = glow.glow_objects(_doc(), _links(_doc(), MATCHED), MESHES)
    (m, s, rgb, k), _ = glow.live(objs, bh.StateFade("red"), 0.0)
    assert (m, s) == (3, 0)
    assert rgb == pytest.approx((0.6, 0.6, 1.2))
    assert k == pytest.approx(1.2)


def test_a_texture_material_with_an_emitter_glows_every_unlinked_mesh():
    d = ld.empty_doc("x")
    d["materials"]["Map 19"] = copy.deepcopy(ROOF)
    d["textures"] = {"map 19.tga": "Map 19"}
    meshes = [{"mesh": 3, "block": 30, "name": "a", "textures": ["Map 19.tga"],
               "maps": {"emissive": False}},
              {"mesh": 4, "block": 40, "name": "b", "textures": ["Map 19.tga"],
               "maps": {"emissive": True}}]
    objs, _ = glow.glow_objects(d, ld.resolve(d, meshes, {}), meshes)
    assert [(m, s) for m, s, _, _ in objs] == [(3, 1), (4, 0)]
