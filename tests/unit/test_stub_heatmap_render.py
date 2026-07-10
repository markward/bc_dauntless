# tests/unit/test_stub_heatmap_render.py
from tools import stub_heatmap


def _rows(*specs):
    # specs: (owner, attr, total, runs_seen, last_seen, marked, status)
    return [{"owner": o, "attr": a, "total": t, "runs_seen": rs,
             "last_seen": ls, "marked": mk, "status": st}
            for (o, a, t, rs, ls, mk, st) in specs]


def test_render_sections_and_determinism():
    rows = _rows(
        ("B", "hot", 500, 1, 1.0, "", "open"),
        ("A", "rare", 3, 1, 1.0, "", "open"),
        ("Foo", "Bar", 9, 1, 5_000_000_000.0, "2026-07-12", "regressed"),
        ("Baz", "Qux", 2, 1, 1.0, "2026-07-11", "resolved"),
    )
    meta = {"M": 1, "date_range": (1.0, 5e9), "line_skipped": 0, "ann_skipped": 0}
    out1 = stub_heatmap.render(rows, [], meta)
    out2 = stub_heatmap.render(rows, [], meta)
    assert out1 == out2                                   # deterministic
    assert out1.index("Regressed") < out1.index("roadmap")  # regressed on top
    assert "Foo" in out1 and "Baz" in out1
    # open roadmap ranks hot before rare; resolved/regressed not in the roadmap
    assert out1.index("hot") < out1.index("rare")
    assert "Open: 2, resolved: 1, regressed: 1" in out1


def test_render_no_regressed_section_when_none():
    rows = _rows(("A", "x", 1, 1, 1.0, "", "open"))
    meta = {"M": 1, "date_range": (1.0, 1.0), "line_skipped": 0, "ann_skipped": 0}
    out = stub_heatmap.render(rows, [], meta)
    assert "Regressed" not in out


def test_render_no_wallclock_now(monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: 9_999_999_999.0)
    rows = _rows(("A", "x", 1, 1, 0.0, "", "open"))
    meta = {"M": 1, "date_range": (0.0, 0.0), "line_skipped": 0, "ann_skipped": 0}
    out = stub_heatmap.render(rows, [], meta)
    assert "9999999999" not in out
    # the date IS derived from the input (epoch 0 -> 1970)
    assert "1970-01-01" in out
