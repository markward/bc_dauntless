# tests/engine/appc/test_sky_projection_realmodel.py
from engine.appc import sky_projection as sp


def test_real_model_projects_from_vesuvi():
    model = sp.load_sector_model()
    assert model["systems"], "sector_model.json must be committed (Task 2)"
    vesuvi = next(s for s in model["systems"] if s["id"] == "vesuvi")
    out = sp.project_sky(vesuvi["position"], model)
    # base starfield + every nebula + every star-cloud
    assert len(out) == 1 + len(model["nebulae"]) + len(model["starclouds"])
    # Vesuvi's own nebula is the nearest -> it renders large (near-field).
    # The exact envelop (distance < radius -> span 8.0) is covered by the
    # Task 4 unit tests; real inferred geometry needn't hard-envelop.
    neb_spans = [d["h_span"] for d in out if d["proc_kind"] == "nebula"]
    assert neb_spans and max(neb_spans) >= 3.0
    # every descriptor is well-formed
    for d in out:
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9
