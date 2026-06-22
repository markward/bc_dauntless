"""The catalog baker registers all systems headlessly and folds warp_points
into the sector model."""
import json

import tools.bake_set_course_catalog as baker


def test_build_catalog_has_systems_and_warp_points():
    catalog = baker.build_catalog()
    assert len(catalog) >= 30
    total = sum(len(v["warp_points"]) for v in catalog.values())
    assert total >= 80
    # Labels are real (from SetClass_MakeDisplayName), each warp has id + label.
    sample = next(iter(catalog.values()))
    wps = sample["warp_points"]
    assert wps and "id" in wps[0] and "label" in wps[0]
    assert "MakeDisplayName" not in wps[0]["label"]


def test_fold_into_model_preserves_systems(tmp_path):
    src = {"systems": [{"id": "vesuvi", "position": [1, 2, 3]}],
           "nebulae": [], "starclouds": []}
    p = tmp_path / "sector_model.json"
    p.write_text(json.dumps(src))
    catalog = {"vesuvi": {"module": "Systems.Vesuvi.Vesuvi4",
                          "warp_points": [{"id": "vesuvi-4",
                                           "label": "Vesuvi 4",
                                           "module": "Systems.Vesuvi.Vesuvi4"}]}}
    baker.fold_into_model(catalog, p)
    out = json.loads(p.read_text())
    v = out["systems"][0]
    assert v["position"] == [1, 2, 3]          # untouched
    assert v["module"] == "Systems.Vesuvi.Vesuvi4"
    assert v["warp_points"] == [{"id": "vesuvi-4", "label": "Vesuvi 4",
                                 "module": "Systems.Vesuvi.Vesuvi4"}]


def test_catalog_carries_destination_modules():
    from tools.bake_set_course_catalog import build_catalog
    import tools.mission_harness as mh
    import sys
    if not any(type(f).__name__ == "_SDKFinder" for f in sys.meta_path):
        mh.setup_sdk()
    catalog = build_catalog()
    vesuvi = catalog["vesuvi"]
    mods = {w["module"] for w in vesuvi["warp_points"]}
    assert "Systems.Vesuvi.Vesuvi4" in mods
    # Riha is a single-region system: its self-entry carries the system module.
    assert catalog["riha"]["module"] == "Systems.Riha.Riha1"
