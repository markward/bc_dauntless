"""Objects -> per-mesh glow (spec §13.2)."""
import copy

import pytest

from engine.bridge_editor import behaviour as bh, glow, lighting_doc as ld, probe_layers as pl

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]
ROOF = {"emission": 0, "modifiers": [
    {"type": "state", "scope": ["green", "red"], "tint": [0.5, 0.5, 1], "level": 1.2}]}


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


def test_the_map_is_the_source_where_there_is_one_else_the_material_says():
    objs, warnings = glow.glow_objects(_doc(), _links(_doc(), MATCHED), MESHES)
    assert [(m, s, has_map) for m, s, _, has_map in objs] == [(3, 0, True), (4, 1, False)]
    assert warnings == []


def test_a_finish_only_material_adds_no_glow():
    objs, _ = glow.glow_objects(_doc(), _links(_doc(), {"12:wall": 5}), MESHES)
    assert objs == []


def test_without_a_map_a_flat_source_glows_flat():
    d = _doc()
    d["materials"]["roof"]["emission_source"] = "flat"
    objs, warnings = glow.glow_objects(d, _links(d, MATCHED), MESHES)
    assert [(m, s) for m, s, _, _ in objs] == [(3, 0), (4, 2)]


def test_an_emission_level_alone_glows():
    """Mark's com lights: a Finish emission level with no modifiers glows."""
    d = _doc()
    d["materials"]["finish only"]["emission"] = 3
    objs, _ = glow.glow_objects(d, _links(d, {"12:wall": 5}), MESHES)
    (_, _, rgb, k), = glow.live(objs, bh.StateFade("yellow"), 0.0)
    assert rgb == (3.0, 3.0, 3.0) and k == 3.0


def test_live_follows_the_state_modifier():
    objs, _ = glow.glow_objects(_doc(), _links(_doc(), MATCHED), MESHES)
    (m, s, rgb, k), _ = glow.live(objs, bh.StateFade("red"), 0.0)
    assert (m, s) == (3, 0)
    assert rgb == pytest.approx((0.6, 0.6, 1.2))
    assert k == pytest.approx(1.2)


def test_the_default_on_a_mapped_mesh_is_the_map_as_painted():
    d = _doc()
    d["materials"]["roof"].pop("emission")
    objs, _ = glow.glow_objects(d, _links(d, MATCHED), MESHES)
    _, (_, _, rgb, _) = glow.live(objs, bh.StateFade("yellow"), 0.0)   # mesh 4: no map
    (_, _, mapped, _), _ = glow.live(objs, bh.StateFade("yellow"), 0.0)
    assert mapped == (1.0, 1.0, 1.0) and rgb == (0.0, 0.0, 0.0)


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


def test_a_lights_only_state_does_not_glow_the_surface():
    """Spec §16.9: a State with "glows": false colours the lights only."""
    d = _doc()
    d["materials"]["roof"]["modifiers"][0]["glows"] = False
    objs, _ = glow.glow_objects(d, _links(d, MATCHED), MESHES)
    live = glow.live(objs, bh.StateFade("green"), 0.0)
    # ROOF sets emission 0: both surfaces stay at that base, not the State's tint.
    for mesh in (3, 4):
        g = [g for g in live if g[0] == mesh][0]
        assert g[2] == (0.0, 0.0, 0.0) and g[3] == 0.0


def _map22a():
    """Map 22a-shaped: a mapped mesh, a red sine pulse (min 0.2), no State."""
    d = ld.empty_doc("x")
    d["materials"]["Map 22a"] = {"modifiers": [
        {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.2}]}
    d["textures"] = {"map 22a.tga": "Map 22a"}
    meshes = [{"mesh": 3, "block": 30, "name": "a", "textures": ["Map 22a.tga"],
               "maps": {"emissive": True}}]
    resolved = ld.resolve(d, meshes, {})
    objs, _ = glow.glow_objects(d, resolved, meshes)
    plan = pl.plan(d, resolved, set(), frozenset({3}), 8)
    return objs, plan


def test_glow_captures_base_and_layer():
    objs, plan = _map22a()
    ((mesh, src, caps, layers, rgbs),) = glow.captures(objs, plan)
    assert (mesh, src) == (3, 0)
    assert caps[0] == (1.0, 1.0, 1.0)          # the map as painted
    assert caps[2] == (0.0, 0.0, 0.0)          # animated in red: the layer carries it
    assert layers == [-1, -1, 0, -1, -1]
    assert rgbs[2] == pytest.approx((1.0, 1.0, 1.0))


def test_glow_live_decoded_equals_layer_decoded_times_value():
    objs, plan = _map22a()
    ((_m, _s, _c, _l, rgbs),) = glow.captures(objs, plan)
    t = 0.75
    ((_, _, live_rgb, _k),) = glow.live(objs, bh.StateFade("red"), t)
    v = pl.layer_values(plan, t)[0]
    for got, base in zip(live_rgb, rgbs[2]):
        assert got ** 2.2 == pytest.approx(base ** 2.2 * v, rel=1e-6)
