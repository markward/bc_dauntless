# tests/unit/test_stub_heatmap_render.py
from tools import stub_heatmap


def test_render_is_deterministic_and_sorted():
    merged = {
        "M": 4,
        "attr": {
            "A\trare": {"total": 3, "runs_seen": 1},
            "B\thot": {"total": 500, "runs_seen": 4},
            "C\tmid": {"total": 500, "runs_seen": 2},  # ties B on total -> key order
        },
        "bool": {"f.py:9": {"total": 20, "runs_seen": 3}},
    }
    series = [2, 1, 0, 0]
    out1 = stub_heatmap.render(merged, series, skipped=1, date_range=(1000.0, 2000.0))
    out2 = stub_heatmap.render(merged, series, skipped=1, date_range=(1000.0, 2000.0))
    assert out1 == out2  # deterministic
    # hottest first; tie broken by key ascending (B\thot before C\tmid)
    assert out1.index("B.hot") < out1.index("C.mid") < out1.index("A.rare")
    # coverage rendered as N/M
    assert "4/4" in out1 and "1/4" in out1
    # display uses dotted form, never the raw tab key
    assert "\t" not in out1
    assert "B.hot" in out1


def test_render_has_no_wallclock_now(monkeypatch):
    # render must derive everything from inputs; guard against a stray time.time()
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: 9_999_999_999.0)
    merged = {"M": 1, "attr": {"A\tx": {"total": 1, "runs_seen": 1}}, "bool": {}}
    out = stub_heatmap.render(merged, [1], skipped=0, date_range=(0.0, 0.0))
    # positive: the date shown must come from date_range (epoch 0), not the clock
    assert "1970-01-01 00:00 UTC" in out
    # negative: the monkeypatched wall-clock sentinel must never leak in
    assert "9999999999" not in out


def test_date_range_none_when_no_timestamps():
    assert stub_heatmap._date_range([{"attr_hits": {}}]) is None
    assert stub_heatmap._date_range([{"t": 5.0, "attr_hits": {}}]) == (5.0, 5.0)


def test_main_no_runs_writes_nothing(tmp_path, capsys):
    out_file = tmp_path / "heatmap.md"
    rc = stub_heatmap.main(["--sidecar", str(tmp_path / "absent.jsonl"),
                            "--out", str(out_file)])
    assert rc == 0
    assert not out_file.exists()
    assert "no runs" in capsys.readouterr().out.lower()


def test_main_writes_heatmap(tmp_path):
    import json
    sidecar = tmp_path / "hits.jsonl"
    with open(sidecar, "w") as f:
        f.write(json.dumps({"t": 1.0, "attr_hits": {"A\tx": 7}, "bool_sites": {}}) + "\n")
    out_file = tmp_path / "heatmap.md"
    rc = stub_heatmap.main(["--sidecar", str(sidecar), "--out", str(out_file)])
    assert rc == 0
    text = out_file.read_text()
    assert "A.x" in text and "1 run" in text.lower()
