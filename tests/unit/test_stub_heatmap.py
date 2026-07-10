import json

from tools import stub_heatmap


def _write(tmp_path, records):
    path = tmp_path / "hits.jsonl"
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return str(path)


def test_load_runs_missing_file_is_empty(tmp_path):
    runs, skipped = stub_heatmap.load_runs(str(tmp_path / "nope.jsonl"))
    assert runs == [] and skipped == 0


def test_load_runs_skips_and_counts_malformed(tmp_path):
    path = tmp_path / "hits.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"attr_hits": {"A\tx": 1}, "bool_sites": {}}) + "\n")
        f.write("{ this is not json\n")
        f.write("\n")  # blank, ignored, not counted as malformed
        f.write(json.dumps(["not", "a", "dict"]) + "\n")  # wrong shape
    runs, skipped = stub_heatmap.load_runs(str(path))
    assert len(runs) == 1
    assert skipped == 2


def test_load_runs_skips_non_dict_attr_hits_value(tmp_path):
    path = tmp_path / "hits.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"attr_hits": ["x"]}) + "\n")  # valid JSON, dict rec,
        # but attr_hits value is a list, not a dict -> must be rejected here
        f.write(json.dumps({"attr_hits": {"A\tx": 1}, "bool_sites": {}}) + "\n")
    runs, skipped = stub_heatmap.load_runs(str(path))
    assert skipped == 1
    assert len(runs) == 1
    assert runs[0]["attr_hits"] == {"A\tx": 1}
    # confirm merge/saturation only ever see the surviving, well-shaped run
    m = stub_heatmap.merge(runs)
    assert m["M"] == 1
    assert m["attr"]["A\tx"] == {"total": 1, "runs_seen": 1}
    assert stub_heatmap.saturation(runs) == [1]


def test_merge_sums_hits_and_counts_coverage(tmp_path):
    path = _write(tmp_path, [
        {"attr_hits": {"TorpedoTube\tGetMaxCharge": 100}, "bool_sites": {"f.py:1": 5}},
        {"attr_hits": {"TorpedoTube\tGetMaxCharge": 50, "A\tx": 3}, "bool_sites": {}},
    ])
    runs, _ = stub_heatmap.load_runs(path)
    m = stub_heatmap.merge(runs)
    assert m["M"] == 2
    assert m["attr"]["TorpedoTube\tGetMaxCharge"] == {"total": 150, "runs_seen": 2}
    assert m["attr"]["A\tx"] == {"total": 3, "runs_seen": 1}
    assert m["bool"]["f.py:1"] == {"total": 5, "runs_seen": 1}


def test_saturation_counts_new_pairs_per_run(tmp_path):
    path = _write(tmp_path, [
        {"attr_hits": {"A\tx": 1, "B\ty": 1}, "bool_sites": {}},   # 2 new
        {"attr_hits": {"A\tx": 1}, "bool_sites": {}},              # 0 new
        {"attr_hits": {"C\tz": 1}, "bool_sites": {}},              # 1 new
    ])
    runs, _ = stub_heatmap.load_runs(path)
    assert stub_heatmap.saturation(runs) == [2, 0, 1]


def test_saturation_verdict_plateau_vs_discovering():
    assert "SATURATED" in stub_heatmap.saturation_verdict([5, 2, 0, 0, 0])
    assert "NOT" in stub_heatmap.saturation_verdict([5, 2, 0, 0, 4])
    assert "NOT" in stub_heatmap.saturation_verdict([1])  # too few runs to call saturated
