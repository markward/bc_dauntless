# Stub Resolution Tracking + Regression Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track resolved stubs and flag regressions inside `docs/stub_heatmap.md` via two per-stub timestamps — `lastSeenOn` (from sidecar run times) and `markedResolvedOn` (hand-entered) — and the rule `lastSeenOn > markedResolvedOn ⇒ ⚠️ regressed`.

**Architecture:** Tool-only change to `tools/stub_heatmap.py`. `lastSeenOn` is computed from the existing `stub_hits.jsonl` (each run has a timestamp `t`). `markedResolvedOn` is preserved across regenerations by reading the prior `docs/stub_heatmap.md` and carrying each annotation forward keyed by the exact `(owner, attr)`. Tables render owner/attr as separate columns so the key round-trips unambiguously. The old "saturation" section is removed (that frame was retired).

**Tech Stack:** Python 3, stdlib only (`json`, `argparse`, `time`, `datetime`, `collections`), pytest.

## Global Constraints

- **Tool-only.** No engine/game/persistence change — only `tools/stub_heatmap.py` and `docs/stub_heatmap.md`'s format, plus the tool's tests.
- **Deterministic output.** Given the same sidecar + the same `markedResolvedOn` annotations, regeneration is byte-identical. No `now()`; every value derives from the sidecar or preserved annotations. Sorting is explicit and total.
- **Preserve annotations across regen.** The generator overwrites the file, so it MUST first read the existing file and carry every `markedResolvedOn` forward by exact `(owner, attr)` key. A regeneration must never silently drop a resolution.
- **Exact key recovery.** Tables render `owner` and `attr` as **separate columns**. The internal key is the tab-joined `"owner\tattr"`; split on the first tab to get columns, rejoin to recover the key.
- **Never crash on a bad hand-edit.** A malformed table row or unparseable `markedResolvedOn` is skipped and counted (surfaced in the header), never aborts the run or drops *all* annotations.
- **Stdlib only.**

## Timestamp semantics (bind both tasks)

- `lastSeenOn(owner, attr)` = the newest `t` among sidecar runs whose `attr_hits` contains that key; `None` if it appears in no timestamped run.
- `markedResolvedOn` accepts `YYYY-MM-DD` (→ **end of that day UTC**, 23:59:59 — so a run *earlier the same day*, before the fix, does not count as a regression) or `YYYY-MM-DD HH:MM` (optionally suffixed ` UTC`).
- Status: **open** if no `markedResolvedOn`; **regressed** if `markedResolvedOn` set and `lastSeenOn > markedResolvedOn`; **resolved** otherwise (including `lastSeenOn` is `None`).

---

### Task 1: Timestamp + status logic (pure functions)

**Files:**
- Modify: `tools/stub_heatmap.py` (add `import datetime`; add `last_seen_by_key`, `parse_resolved_date`, `classify`)
- Test: `tests/unit/test_stub_heatmap_resolution.py`

**Interfaces:**
- Consumes: sidecar run dicts (as `load_runs` returns).
- Produces:
  - `last_seen_by_key(runs: list) -> dict` — `{ "owner\tattr": epoch_float }`, newest `t` per key; runs with a non-numeric `t` contribute nothing.
  - `parse_resolved_date(s: str | None) -> datetime.datetime | None` — UTC, end-of-day for a bare date; `None` for empty/invalid.
  - `classify(last_seen_epoch: float | None, marked_resolved_str: str) -> str` — `"open"` | `"resolved"` | `"regressed"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_heatmap_resolution.py
import datetime

from tools import stub_heatmap


def test_last_seen_by_key_takes_newest_timestamp():
    runs = [
        {"t": 100.0, "attr_hits": {"A\tx": 1, "B\ty": 1}},
        {"t": 200.0, "attr_hits": {"A\tx": 1}},
        {"t": 50.0, "attr_hits": {"A\tx": 1}},
    ]
    ls = stub_heatmap.last_seen_by_key(runs)
    assert ls["A\tx"] == 200.0   # newest, not most recent in list order
    assert ls["B\ty"] == 100.0


def test_last_seen_ignores_runs_without_numeric_timestamp():
    runs = [{"attr_hits": {"A\tx": 1}}, {"t": "bad", "attr_hits": {"A\tx": 1}}]
    assert stub_heatmap.last_seen_by_key(runs) == {}


def test_parse_resolved_date_bare_date_is_end_of_day_utc():
    d = stub_heatmap.parse_resolved_date("2026-07-15")
    assert d == datetime.datetime(2026, 7, 15, 23, 59, 59, tzinfo=datetime.timezone.utc)


def test_parse_resolved_date_full_and_invalid():
    assert stub_heatmap.parse_resolved_date("2026-07-15 09:30") == \
        datetime.datetime(2026, 7, 15, 9, 30, tzinfo=datetime.timezone.utc)
    assert stub_heatmap.parse_resolved_date("2026-07-15 09:30 UTC") == \
        datetime.datetime(2026, 7, 15, 9, 30, tzinfo=datetime.timezone.utc)
    assert stub_heatmap.parse_resolved_date("") is None
    assert stub_heatmap.parse_resolved_date(None) is None
    assert stub_heatmap.parse_resolved_date("not-a-date") is None


def test_classify_open_resolved_regressed():
    # epoch for 2026-07-15 12:00 UTC
    noon = datetime.datetime(2026, 7, 15, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
    # open: no resolved date
    assert stub_heatmap.classify(noon, "") == "open"
    # resolved: last hit is BEFORE the resolved day
    assert stub_heatmap.classify(noon, "2026-07-16") == "resolved"
    # resolved: never seen
    assert stub_heatmap.classify(None, "2026-07-16") == "resolved"
    # regressed: last hit AFTER the resolved day
    assert stub_heatmap.classify(noon, "2026-07-14") == "regressed"


def test_classify_same_day_before_fix_is_not_a_regression():
    # a run at 09:00 on the day you marked resolved must NOT regress (end-of-day)
    nine_am = datetime.datetime(2026, 7, 15, 9, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert stub_heatmap.classify(nine_am, "2026-07-15") == "resolved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_heatmap_resolution.py -v`
Expected: FAIL — `AttributeError: module 'tools.stub_heatmap' has no attribute 'last_seen_by_key'`.

- [ ] **Step 3: Write minimal implementation**

Add `import datetime` to the imports in `tools/stub_heatmap.py` (alongside `argparse`, `json`, `time`):

```python
import argparse
import datetime
import json
import time
from collections import Counter
```

Add these three functions (near the other helpers):

```python
def last_seen_by_key(runs: "list") -> dict:
    """Newest run timestamp `t` among runs that hit each attr key.

    Returns {"owner\\tattr": epoch_float}. Runs whose `t` is missing or
    non-numeric contribute nothing (their hits have no usable time)."""
    out: dict = {}
    for rec in runs:
        t = rec.get("t")
        if not isinstance(t, (int, float)):
            continue
        for k in (rec.get("attr_hits") or {}):
            if k not in out or t > out[k]:
                out[k] = t
    return out


def parse_resolved_date(s):
    """Parse a markedResolvedOn cell to a UTC datetime, or None.

    'YYYY-MM-DD' -> end of that day UTC (23:59:59) so a run earlier the same
    day (before the fix) is not a regression. 'YYYY-MM-DD HH:MM' (optionally
    with a trailing ' UTC') -> that minute UTC. Empty/invalid -> None."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    if s.endswith("UTC"):
        s = s[:-3].strip()
    try:
        if len(s) == 10:
            d = datetime.datetime.strptime(s, "%Y-%m-%d")
            return d.replace(hour=23, minute=59, second=59,
                             tzinfo=datetime.timezone.utc)
        d = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M")
        return d.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def classify(last_seen_epoch, marked_resolved_str: str) -> str:
    """'open' (unresolved) | 'resolved' (quiet) | 'regressed' (hit after fix)."""
    resolved_dt = parse_resolved_date(marked_resolved_str)
    if resolved_dt is None:
        return "open"
    if last_seen_epoch is None:
        return "resolved"
    last_dt = datetime.datetime.fromtimestamp(
        last_seen_epoch, tz=datetime.timezone.utc)
    return "regressed" if last_dt > resolved_dt else "resolved"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_heatmap_resolution.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/stub_heatmap.py tests/unit/test_stub_heatmap_resolution.py
git commit -m "feat(telemetry): stub last-seen + resolved-date classification logic"
```

---

### Task 2: Heatmap format overhaul — annotations, sections, regen preservation

**Files:**
- Modify: `tools/stub_heatmap.py` (add `_split_row`, `parse_existing_annotations`, `build_rows`; rewrite `render`; rewrite `main`; remove `saturation`, `saturation_verdict`)
- Modify: `tests/unit/test_stub_heatmap.py` (remove the two saturation tests)
- Modify: `tests/unit/test_stub_heatmap_render.py` (rewrite for the new render signature/format)
- Test: `tests/unit/test_stub_heatmap_annotations.py`

**Interfaces:**
- Consumes: `merge` (Task/Piece-1), `last_seen_by_key`, `classify` (Task 1), `load_runs`, `_date_range`, `_fmt_ts`.
- Produces:
  - `_split_row(line: str) -> list[str]` — cells of a markdown table row (outer pipes stripped).
  - `parse_existing_annotations(path: str) -> tuple[dict, int]` — `({(owner, attr): markedResolvedOn}, skipped)`. Reads any table having `owner`, `attr`, and `markedResolvedOn` columns (by header). Missing file / old format → `({}, 0)`.
  - `build_rows(merged: dict, last_seen: dict, resolved_map: dict) -> list[dict]` — one dict per attr key: `{owner, attr, total, runs_seen, last_seen, marked, status}`.
  - `render(attr_rows: list, bool_rows: list, meta: dict) -> str` — deterministic markdown: header, ⚠️ Regressed (if any), Roadmap (open), Resolved, Boolean-test call sites.
  - `main` — reads existing annotations, builds rows, writes the file.

- [ ] **Step 1: Write the failing tests (annotations + round-trip)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_heatmap_annotations.py -v`
Expected: FAIL — `AttributeError: module 'tools.stub_heatmap' has no attribute '_split_row'`.

- [ ] **Step 3: Write minimal implementation**

In `tools/stub_heatmap.py`, **delete** `saturation` and `saturation_verdict` (both are retired with the saturation frame). Add the parsing/assembly helpers and rewrite `render` and `main`.

Add helpers:

```python
def _split_row(line: str) -> "list":
    """Cells of a markdown table row; outer pipes dropped, inner cells kept raw."""
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return parts


def _is_separator(line: str) -> bool:
    return line.strip().startswith("|") and all(ch in "-|: " for ch in line)


def parse_existing_annotations(path: str) -> "tuple[dict, int]":
    """Extract {(owner, attr): markedResolvedOn} from an existing heatmap.

    Reads any table whose header has 'owner', 'attr', and 'markedresolvedon'
    columns (the Regressed + Resolved sections). Missing file or old-format
    file -> ({}, 0). Rows with a short/garbled cell count are skipped and
    counted; a single bad row never drops the rest."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return {}, 0
    out: dict = {}
    skipped = 0
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < n and _is_separator(lines[i + 1]):
            header = [c.strip().lower() for c in _split_row(line)]
            cols = {name: idx for idx, name in enumerate(header)}
            j = i + 2
            if all(c in cols for c in ("owner", "attr", "markedresolvedon")):
                while j < n and lines[j].strip().startswith("|") and not _is_separator(lines[j]):
                    cells = _split_row(lines[j])
                    try:
                        owner = cells[cols["owner"]].strip()
                        attr = cells[cols["attr"]].strip()
                        marked = cells[cols["markedresolvedon"]].strip()
                        if owner and attr and marked and marked not in ("—", "-"):
                            out[(owner, attr)] = marked
                    except Exception:
                        skipped += 1
                    j += 1
            else:
                while j < n and lines[j].strip().startswith("|") and not _is_separator(lines[j]):
                    j += 1
            i = j
            continue
        i += 1
    return out, skipped


def build_rows(merged: dict, last_seen: dict, resolved_map: dict) -> "list":
    """One row dict per attr key, classified and carrying its annotation."""
    rows = []
    for key, v in merged["attr"].items():
        owner, _, attr = key.partition("\t")
        marked = resolved_map.get((owner, attr), "")
        ls = last_seen.get(key)
        rows.append({
            "owner": owner, "attr": attr,
            "total": v["total"], "runs_seen": v["runs_seen"],
            "last_seen": ls, "marked": marked,
            "status": classify(ls, marked),
        })
    return rows
```

Replace `render` entirely:

```python
def _ls(epoch) -> str:
    return _fmt_ts(epoch) if isinstance(epoch, (int, float)) else "—"


def render(attr_rows: "list", bool_rows: "list", meta: dict) -> str:
    M = meta["M"]
    regressed = [r for r in attr_rows if r["status"] == "regressed"]
    openr = [r for r in attr_rows if r["status"] == "open"]
    resolved = [r for r in attr_rows if r["status"] == "resolved"]
    regressed.sort(key=lambda r: (-r["total"], r["owner"], r["attr"]))
    openr.sort(key=lambda r: (-r["total"], r["owner"], r["attr"]))
    resolved.sort(key=lambda r: (r["marked"], r["owner"], r["attr"]))

    L = ["# Stub Telemetry Heatmap", ""]
    run_word = "run" if M == 1 else "runs"
    header = "Accumulated from **%d %s**" % (M, run_word)
    if meta.get("date_range") is not None:
        header += " (%s .. %s)" % (_fmt_ts(meta["date_range"][0]), _fmt_ts(meta["date_range"][1]))
    header += ". Open: %d, resolved: %d, regressed: %d." % (len(openr), len(resolved), len(regressed))
    if meta.get("line_skipped"):
        header += " Skipped %d malformed sidecar line(s)." % meta["line_skipped"]
    if meta.get("ann_skipped"):
        header += " Skipped %d malformed annotation row(s)." % meta["ann_skipped"]
    L += [header, ""]
    L += ["_Regression check: a resolved stub hit again (lastSeenOn > markedResolvedOn) is flagged below._", ""]

    if regressed:
        L += ["## ⚠️ Regressed (hit again after being marked resolved)", ""]
        L += ["| owner | attr | markedResolvedOn | lastSeenOn | hits |", "|---|---|---|---|---|"]
        for r in regressed:
            L.append("| %s | %s | %s | %s | %d |" % (r["owner"], r["attr"], r["marked"], _ls(r["last_seen"]), r["total"]))
        L.append("")

    L += ["## Unimplemented-attribute roadmap (open)", ""]
    L += ["| rank | owner | attr | total hits | coverage | lastSeenOn |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(openr, 1):
        L.append("| %d | %s | %s | %d | %d/%d | %s |" % (i, r["owner"], r["attr"], r["total"], r["runs_seen"], M, _ls(r["last_seen"])))
    L.append("")

    L += ["## Resolved", ""]
    L += ["| owner | attr | markedResolvedOn | lastSeenOn |", "|---|---|---|---|"]
    for r in resolved:
        L.append("| %s | %s | %s | %s |" % (r["owner"], r["attr"], r["marked"], _ls(r["last_seen"])))
    L.append("")

    L += ["## Boolean-test call sites (truthiness risk)", ""]
    L += ["| rank | file:line | total hits | coverage |", "|---|---|---|---|"]
    for i, b in enumerate(sorted(bool_rows, key=lambda b: (-b["total"], b["site"])), 1):
        L.append("| %d | %s | %d | %d/%d |" % (i, b["site"], b["total"], b["runs_seen"], M))
    L.append("")
    return "\n".join(L)
```

Replace `main` entirely:

```python
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Merge stub_hits.jsonl into a heatmap.")
    p.add_argument("--sidecar", default="stub_hits.jsonl")
    p.add_argument("--out", default="docs/stub_heatmap.md")
    args = p.parse_args(argv)
    runs, line_skipped = load_runs(args.sidecar)
    if not runs:
        print("no runs accumulated yet (sidecar: %s)" % args.sidecar)
        return 0
    resolved_map, ann_skipped = parse_existing_annotations(args.out)
    merged = merge(runs)
    last_seen = last_seen_by_key(runs)
    attr_rows = build_rows(merged, last_seen, resolved_map)
    bool_rows = [{"site": k, "total": v["total"], "runs_seen": v["runs_seen"]}
                 for k, v in merged["bool"].items()]
    meta = {"M": merged["M"], "date_range": _date_range(runs),
            "line_skipped": line_skipped, "ann_skipped": ann_skipped}
    text = render(attr_rows, bool_rows, meta)
    with open(args.out, "w") as f:
        f.write(text)
    n_reg = sum(1 for r in attr_rows if r["status"] == "regressed")
    print("wrote %s (%d runs, %d stubs, %d regressed)"
          % (args.out, merged["M"], len(attr_rows), n_reg))
    return 0
```

- [ ] **Step 4: Update the tests that referenced the removed render signature / saturation**

In `tests/unit/test_stub_heatmap.py`, DELETE `test_saturation_counts_new_pairs_per_run` and `test_saturation_verdict_plateau_vs_discovering` (the functions they test are removed). Leave the `load_runs`/`merge` tests unchanged.

Replace the entire body of `tests/unit/test_stub_heatmap_render.py` with tests for the new render:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_stub_heatmap_annotations.py tests/unit/test_stub_heatmap_render.py tests/unit/test_stub_heatmap.py tests/unit/test_stub_heatmap_resolution.py -v`
Expected: PASS. Confirm the two saturation tests are gone (not failing).

- [ ] **Step 6: End-to-end main test (regression surfaces across regen)**

Append to `tests/unit/test_stub_heatmap_annotations.py`:

```python
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
```

Run: `uv run pytest tests/unit/test_stub_heatmap_annotations.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. All changes are offline tooling; nothing that runs by default in the game changed.

- [ ] **Step 8: Commit**

```bash
git add tools/stub_heatmap.py tests/unit/test_stub_heatmap.py tests/unit/test_stub_heatmap_render.py tests/unit/test_stub_heatmap_annotations.py
git commit -m "feat(telemetry): resolution tracking + regression flag in the heatmap"
```

---

## Self-Review

**1. Spec coverage.** (a) `lastSeenOn` from sidecar `t` → `last_seen_by_key` (Task 1); (b) `markedResolvedOn` end-of-day date semantics → `parse_resolved_date` (Task 1); (c) open/resolved/regressed status → `classify` (Task 1) + `build_rows` (Task 2); (d) separate owner/attr columns for exact key recovery → render + `parse_existing_annotations` + the dotted-key round-trip test (Task 2); (e) preserve annotations across regen → `parse_existing_annotations` + `main` (Task 2); (f) three sections + resolved-stays-in-file → render (Task 2); (g) malformed tolerance (bad row/date, old format) → `parse_existing_annotations` skip+count, `parse_resolved_date` → None, `test_parse_existing_annotations_missing_file`; (h) deterministic, no `now()` → `test_render_no_wallclock_now`; (i) saturation removed → deletions in Task 2. Bool-site resolution and any engine change are correctly out of scope.

**2. Placeholder scan.** No TBD/TODO; every code step is complete; all referenced names (`last_seen_by_key`, `parse_resolved_date`, `classify`, `_split_row`, `_is_separator`, `parse_existing_annotations`, `build_rows`, `_ls`, `render`, `main`) are defined in the task that introduces them.

**3. Type consistency.** `build_rows` emits row dicts with keys `{owner, attr, total, runs_seen, last_seen, marked, status}`; `render` consumes exactly those. `parse_existing_annotations` returns `({(owner, attr): str}, int)`, consumed by `main` and fed to `build_rows` as `resolved_map`. `last_seen_by_key` returns `{tab_key: epoch}`, consumed by `build_rows` via the same tab key `merge` uses. `bool_rows` are `{site, total, runs_seen}` dicts, built in `main`, consumed by `render`.

**Note for the executor:** confirm the current text of `tools/stub_heatmap.py` before editing (match on the code shown). After Task 2, regenerating `docs/stub_heatmap.md` reformats it to the new layout — expected. The end-to-end test in Step 6 injects a Resolved table by hand to simulate a human annotation; keep its structure (header row + separator + data row) exact so `parse_existing_annotations` reads it.
