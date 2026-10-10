"""Per-bridge document -> per-shape glow (spec §11.2)."""
import pytest

from engine.bridge_editor import glow, lighting_doc as ld, profiles

MESHES = [{"mesh": 3, "maps": {"emissive": True}}, {"mesh": 4, "maps": {"emissive": False}}]


def _doc():
    d = ld.empty_doc("x")
    d["profiles"]["roof"] = {"green": {"tint": [1, 1, 1], "level": 1},
                             "red": {"tint": [0.5, 0.5, 1], "level": 0.6}}
    ld.shape_entry(d, 10, "panel")["emitter"] = {"profile": "roof", "phase": 0.25,
                                                 "glow": {"src": "emissive", "scale": 2}}
    ld.shape_entry(d, 11, "alcove")["emitter"] = {"glow": {"src": "texture"}}
    ld.shape_entry(d, 12, "lamp")["emitter"] = {"light": {"position": [0, 0, 0],
                                                          "direction": [0, 0, -1]}}
    return d


MATCHED = {"10:panel": 3, "11:alcove": 4, "12:lamp": 5}


def test_glow_shapes_lists_every_glow_in_mesh_order():
    shapes, warnings = glow.glow_shapes(_doc(), MATCHED, MESHES)
    assert [(m, s, ph, sc) for m, s, _, ph, sc in shapes] == [(3, 0, 0.25, 2.0), (4, 1, 0.0, 1.0)]
    assert shapes[1][2] is profiles.STEADY_WHITE
    assert warnings == []


def test_emissive_src_without_a_map_is_skipped_with_a_warning():
    d = _doc()
    d["shapes"]["11:alcove"]["emitter"]["glow"]["src"] = "emissive"
    shapes, warnings = glow.glow_shapes(d, MATCHED, MESHES)
    assert [s[0] for s in shapes] == [3]
    assert warnings == ["11:alcove: glow src 'emissive' but its albedo has no "
                        "_emissive map; skipped"]


def test_live_scales_the_evaluated_state():
    shapes, _ = glow.glow_shapes(_doc(), MATCHED, MESHES)
    out = glow.live(shapes, profiles.AlertFade(2), 0.0)
    assert out[0][0:2] == (3, 0)
    assert out[0][2] == pytest.approx((0.6, 0.6, 1.2))     # tint x level x scale 2
    assert out[0][3] == pytest.approx(1.2)
    assert out[1] == (4, 1, (1.0, 1.0, 1.0), 1.0)          # steady white
