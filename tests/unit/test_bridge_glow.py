"""Objects -> per-mesh glow (spec §13.2)."""
import copy

import pytest

from engine.bridge_editor import behaviour as bh, glow, lighting_doc as ld

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]
ROOF = {"surface": {"src": "auto", "strength": 2}, "modifiers": [
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


def test_auto_surface_resolves_per_object():
    objs, warnings = glow.glow_objects(_doc(), MATCHED, MESHES)
    assert [(m, s, st) for m, s, _, st in objs] == [(3, 0, 2.0), (4, 1, 2.0)]
    assert warnings == []


def test_a_material_without_emitters_adds_no_glow():
    objs, _ = glow.glow_objects(_doc(), {"12:wall": 5}, MESHES)
    assert objs == []


def test_emission_surface_without_a_map_is_skipped_with_a_warning():
    d = _doc()
    d["materials"]["roof"]["surface"]["src"] = "emission"
    objs, warnings = glow.glow_objects(d, MATCHED, MESHES)
    assert [o[0] for o in objs] == [3]
    assert warnings == ["11:alcove: material 'roof' glows through an emission map but "
                        "this object's texture has none; skipped"]


def test_none_surface_adds_no_glow():
    d = _doc()
    d["materials"]["roof"]["surface"]["src"] = "none"
    assert glow.glow_objects(d, MATCHED, MESHES)[0] == []


def test_live_scales_by_strength():
    objs, _ = glow.glow_objects(_doc(), MATCHED, MESHES)
    (m, s, rgb, k), _ = glow.live(objs, bh.StateFade("red"), 0.0)
    assert (m, s) == (3, 0)
    assert rgb == pytest.approx((0.6, 0.6, 1.2))
    assert k == pytest.approx(1.2)
