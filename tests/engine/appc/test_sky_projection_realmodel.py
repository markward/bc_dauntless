# tests/engine/appc/test_sky_projection_realmodel.py
from engine.appc import sky_projection as sp


def test_real_model_projects_from_vesuvi():
    model = sp.load_sector_model()
    assert model["systems"], "sector_model.json must be committed (Task 2)"
    vesuvi = next(s for s in model["systems"] if s["id"] == "vesuvi")
    out = sp.project_sky(vesuvi["position"], model)
    # base starfield + every nebula + every star-cloud
    assert len(out) == 1 + len(model["nebulae"]) + len(model["starclouds"])
    # at least one feature is near/large from vesuvi (its own nebula)
    assert any(d["proc_kind"] == "nebula" and d["h_span"] >= 8.0 for d in out)
    # every descriptor is well-formed
    for d in out:
        assert d["texture_path"] == "" and len(d["world_rotation"]) == 9
