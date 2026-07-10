# tests/unit/test_stub_heatmap_annotations.py
from tools import stub_heatmap


def test_split_row():
    assert stub_heatmap._split_row("| a | b | c |") == [" a ", " b ", " c "]


def test_parse_existing_annotations_missing_file(tmp_path):
    m, skipped = stub_heatmap.parse_existing_annotations(str(tmp_path / "nope.md"))
    assert m == {} and skipped == 0


def test_parse_existing_annotations_reads_owner_attr_markedresolvedon(tmp_path):
    md = "\n".join([
        "## Resolved",
        "",
        "| owner | attr | markedResolvedOn | lastSeenOn |",
        "|---|---|---|---|",
        "| ShipClass | GetWarpCore.GetMaxPower | 2026-07-12 | 2026-07-09 20:00 UTC |",
        "| Foo | Bar | 2026-07-11 | — |",
        "",
        "## Unimplemented-attribute roadmap",
        "",
        "| rank | owner | attr | total hits | coverage | lastSeenOn |",
        "|---|---|---|---|---|---|",
        "| 1 | Open | Thing | 5 | 1/1 | 2026-07-10 22:00 UTC |",
    ])
    path = tmp_path / "heatmap.md"
    path.write_text(md)
    m, skipped = stub_heatmap.parse_existing_annotations(str(path))
    # dotted attr preserved exactly; roadmap table (no markedResolvedOn col) ignored
    assert m[("ShipClass", "GetWarpCore.GetMaxPower")] == "2026-07-12"
    assert m[("Foo", "Bar")] == "2026-07-11"
    assert ("Open", "Thing") not in m


def test_build_rows_classifies_and_carries_annotations():
    merged = {"M": 2, "attr": {
        "TorpedoTube\tGetMaxCharge": {"total": 100, "runs_seen": 2},
        "Foo\tBar": {"total": 3, "runs_seen": 1},
    }, "bool": {}}
    # TorpedoTube last hit way back; Foo hit recently
    last_seen = {"TorpedoTube\tGetMaxCharge": 100.0, "Foo\tBar": 5_000_000_000.0}
    resolved = {("TorpedoTube", "GetMaxCharge"): "2026-07-12"}  # resolved, old hit
    rows = {(r["owner"], r["attr"]): r for r in
            stub_heatmap.build_rows(merged, last_seen, resolved)}
    assert rows[("TorpedoTube", "GetMaxCharge")]["status"] == "resolved"
    assert rows[("Foo", "Bar")]["status"] == "open"
    assert rows[("Foo", "Bar")]["marked"] == ""


def test_render_then_parse_round_trips_annotations(tmp_path):
    # a resolved row must survive: render -> parse recovers its markedResolvedOn
    merged = {"M": 1, "attr": {"A.B\tC.D": {"total": 1, "runs_seen": 1}}, "bool": {}}
    last_seen = {"A.B\tC.D": 1.0}  # 1970, before the resolved date -> resolved
    resolved = {("A.B", "C.D"): "2026-07-12"}
    rows = stub_heatmap.build_rows(merged, last_seen, resolved)
    meta = {"M": 1, "date_range": (1.0, 1.0), "line_skipped": 0, "ann_skipped": 0}
    text = stub_heatmap.render(rows, [], meta)
    path = tmp_path / "heatmap.md"
    path.write_text(text)
    m, _ = stub_heatmap.parse_existing_annotations(str(path))
    # exact key with dots on BOTH owner and attr survives the round-trip
    assert m[("A.B", "C.D")] == "2026-07-12"


def test_render_flags_regression_and_is_deterministic():
    merged = {"M": 1, "attr": {"Foo\tBar": {"total": 9, "runs_seen": 1}}, "bool": {}}
    last_seen = {"Foo\tBar": 5_000_000_000.0}  # 2128, after resolved date
    resolved = {("Foo", "Bar"): "2026-07-12"}
    rows = stub_heatmap.build_rows(merged, last_seen, resolved)
    meta = {"M": 1, "date_range": (5e9, 5e9), "line_skipped": 0, "ann_skipped": 0}
    out1 = stub_heatmap.render(rows, [], meta)
    out2 = stub_heatmap.render(rows, [], meta)
    assert out1 == out2
    assert "Regressed" in out1 and "Foo" in out1


def test_main_end_to_end_regression_across_regen(tmp_path):
    import json
    sidecar = tmp_path / "hits.jsonl"
    out = tmp_path / "heatmap.md"
    # A prior heatmap already marks Foo.Bar resolved as of 1970-01-01.
    out.write_text(
        "## Resolved\n\n"
        "| owner | attr | markedResolvedOn | lastSeenOn |\n"
        "|---|---|---|---|\n"
        "| Foo | Bar | 1970-01-01 |  |\n"
    )
    # A new run hits Foo.Bar again, well after that resolved date.
    with open(sidecar, "w") as f:
        f.write(json.dumps({"t": 5_000_000_000.0, "attr_hits": {"Foo\tBar": 1}, "bool_sites": {}}) + "\n")
    assert stub_heatmap.main(["--sidecar", str(sidecar), "--out", str(out)]) == 0
    final = out.read_text()
    # annotation preserved from the prior file + a newer hit -> flagged
    assert "Regressed" in final and "regressed: 1" in final
