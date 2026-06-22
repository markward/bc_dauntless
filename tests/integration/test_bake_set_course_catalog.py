"""The catalog baker registers all systems headlessly and folds warp_points
into the sector model."""
import json

import tools.bake_set_course_catalog as baker


def test_build_catalog_has_systems_and_warp_points():
    catalog = baker.build_catalog()
    assert len(catalog) >= 30
    total = sum(len(v) for v in catalog.values())
    assert total >= 80
    # Labels are real (from SetClass_MakeDisplayName), each warp has id + label.
    sample = next(iter(catalog.values()))
    assert sample and "id" in sample[0] and "label" in sample[0]
    assert "MakeDisplayName" not in sample[0]["label"]


def test_fold_into_model_preserves_systems(tmp_path):
    src = {"systems": [{"id": "vesuvi", "position": [1, 2, 3]}],
           "nebulae": [], "starclouds": []}
    p = tmp_path / "sector_model.json"
    p.write_text(json.dumps(src))
    catalog = {"vesuvi": [{"id": "vesuvi-4", "label": "Vesuvi 4"}]}
    baker.fold_into_model(catalog, p)
    out = json.loads(p.read_text())
    v = out["systems"][0]
    assert v["position"] == [1, 2, 3]          # untouched
    assert v["warp_points"] == [{"id": "vesuvi-4", "label": "Vesuvi 4"}]
