import math
from engine.appc import sky_projection as sp


def _model():
    return {"systems": [],
            "nebulae": [
                {"position": [0.0, 0.0, 0.0], "radius": 30.0, "color": [0.9, 0.2, 0.8]},  # near-field (at vantage)
                {"position": [200.0, 0.0, 0.0], "radius": 20.0, "color": [0.3, 0.6, 0.9]},  # far, +X
            ],
            "starclouds": [{"position": [0.0, 300.0, 0.0], "size": 40.0, "color": [0.4, 0.4, 0.5]}]}


def test_includes_base_starfield():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    stars = [d for d in out if d["proc_kind"] == "stars"]
    assert len(stars) == 1
    assert stars[0]["kind"] == "star"


def test_near_field_nebula_envelops():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    # the nebula at the vantage (distance 0 < radius) fills the sphere
    near = [d for d in out if d["proc_kind"] == "nebula" and d["h_span"] >= 8.0]
    assert len(near) == 1


def test_far_nebula_direction_and_falloff():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    far = [d for d in out if d["proc_kind"] == "nebula" and d["h_span"] < 8.0][0]
    # forward column (cols 3,4,5 of the column-major mat3) points +X toward [200,0,0]
    fwd = far["world_rotation"][3:6]
    assert fwd[0] > 0.99
    # dimmed by distance (colour scaled below its source 0.9 red)
    assert far["color"][2] < 0.9
    assert far["h_span"] < 8.0 and far["h_span"] > 0.0


def test_starcloud_projected():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    sc = [d for d in out if d["proc_kind"] == "starcloud"]
    assert len(sc) == 1 and sc[0]["kind"] == "backdrop"


def test_descriptor_has_full_shape():
    out = sp.project_sky([0.0, 0.0, 0.0], _model())
    for d in out:
        for key in ("texture_path", "kind", "h_tile", "v_tile", "h_span", "v_span",
                    "world_rotation", "target_poly_count", "proc_kind", "color", "coverage", "seed"):
            assert key in d, key
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9 and len(d["color"]) == 3
