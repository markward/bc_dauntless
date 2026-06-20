# tests/engine/appc/test_sky_projection_realmodel.py
from engine.appc import sky_projection as sp


def test_real_model_projects_from_vesuvi():
    model = sp.load_sector_model()
    assert model["systems"], "sector_model.json must be committed (Task 2)"
    vesuvi = next(s for s in model["systems"] if s["id"] == "vesuvi")
    out = sp.project_sky(vesuvi["position"], model)
    # base starfield + every nebula + every star-cloud
    assert len(out) == 1 + len(model["nebulae"]) + len(model["starclouds"])
    # Projection's defining property, verified on real data: the nebula nearest
    # the vantage renders largest (span ~ extent / distance). No magic threshold.
    # (The hard near-field envelop at distance < radius is covered by the unit
    # tests in tests/engine/appc/test_sky_projection_project.py.)
    import math
    nebs = model["nebulae"]
    nearest_idx = min(range(len(nebs)),
                      key=lambda i: math.dist(nebs[i]["position"], vesuvi["position"]))
    # project_sky emits nebula descriptors in model order, after the base starfield
    neb_spans = [d["h_span"] for d in out if d["proc_kind"] == "nebula"]
    assert neb_spans, "expected projected nebulae"
    assert neb_spans[nearest_idx] == max(neb_spans)
    # every descriptor is well-formed
    for d in out:
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9
