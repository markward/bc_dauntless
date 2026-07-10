# Stub-Telemetry Accumulation + Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Step 0's per-run stub telemetry into a gitignored JSONL sidecar, and add an offline `tools/` generator that merges across runs into a committed, deterministic heatmap (hit counts + per-pair coverage + a saturation signal).

**Architecture:** Extend `engine/core/stub_telemetry.py` so that, when telemetry is enabled, the existing `atexit` handler appends one JSON line per run to a sidecar (path pinned to an absolute default at import time to survive GLFW's macOS chdir). A new `tools/stub_heatmap.py` reads the sidecar with pure, unit-testable functions and renders `docs/stub_heatmap.md`. Nothing here makes any failure loud — it is observation only, off by default.

**Tech Stack:** Python 3 (embedded CPython host), stdlib only (`json`, `os`, `sys`, `time`, `atexit`, `argparse`, `collections`), pytest.

## Global Constraints

- **OFF by default; production byte-identical.** Persistence happens only when `DAUNTLESS_STUB_TELEMETRY=1`. Env var unset → no file touched, behavior identical to today.
- **Never crashes the game.** Every game-side write is wrapped in `try/except Exception: pass`; a persistence failure never propagates into the game loop.
- **Stdlib only.** No third-party dependencies.
- **Deterministic committed output.** `docs/stub_heatmap.md` contains no `now()`-derived value; every value derives from the sidecar data, so regenerating on the same sidecar yields a byte-identical file. Sorting is `(-total, key)` — count descending, key ascending for ties.
- **Append-only accumulation.** The game only appends to the sidecar; only the tools script reads it. No read-modify-write.
- **Pair key encoding.** `(owner, attr)` is stored as a single tab-separated string `"owner\tattr"` (class names have no tab; `attr` may contain dots from chained breadcrumbs, so a dot-join is ambiguous). Split on the first tab to recover the pair; render for display as `owner.attr`.

---

### Task 1: Game-side per-run persistence

**Files:**
- Modify: `engine/core/stub_telemetry.py` (add imports, `SIDECAR_PATH`, `persist_run`; extend `_atexit_dump`)
- Modify: `.gitignore` (add `stub_hits.jsonl`)
- Test: `tests/unit/test_stub_telemetry_persist.py`

**Interfaces:**
- Consumes: the existing module globals `_attr_hits`, `_bool_sites`, `_atexit_dump` (already present).
- Produces:
  - `SIDECAR_PATH: str` — absolute default sidecar path, resolved at import time.
  - `persist_run(path: str | None = None) -> None` — append one JSON line describing the current counters; `None` → `SIDECAR_PATH`. Never raises. Writes `{"t": float, "attr_hits": {"owner\tattr": count}, "bool_sites": {"file:line": count}}`.
  - `_atexit_dump` also calls `persist_run()` after `dump_report()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_telemetry_persist.py
import json
import os

import pytest

from engine.core import stub_telemetry


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_persist_run_writes_one_valid_json_line(tmp_path):
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("TorpedoTube", "GetMaxCharge")
    stub_telemetry.record_attr("TorpedoTube", "GetMaxCharge")
    stub_telemetry.record_attr("ShipClass", "GetWarpCore.GetMaxPower")  # dotted attr
    path = str(tmp_path / "hits.jsonl")

    stub_telemetry.persist_run(path)

    with open(path) as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert isinstance(rec["t"], float)
    # pair key is tab-separated so a dotted attr is unambiguous
    assert rec["attr_hits"]["TorpedoTube\tGetMaxCharge"] == 2
    assert rec["attr_hits"]["ShipClass\tGetWarpCore.GetMaxPower"] == 1


def test_persist_run_appends_a_line_per_call(tmp_path):
    stub_telemetry.set_enabled(True)
    path = str(tmp_path / "hits.jsonl")
    stub_telemetry.record_attr("A", "x")
    stub_telemetry.persist_run(path)
    stub_telemetry.reset()
    stub_telemetry.record_attr("B", "y")
    stub_telemetry.persist_run(path)
    with open(path) as f:
        assert len(f.read().splitlines()) == 2


def test_persist_run_never_raises_on_bad_path():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("A", "x")
    # a path whose parent directory does not exist must be swallowed
    stub_telemetry.persist_run("/no/such/dir/hits.jsonl")


def test_sidecar_path_is_absolute():
    assert os.path.isabs(stub_telemetry.SIDECAR_PATH)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_telemetry_persist.py -v`
Expected: FAIL — `AttributeError: module 'engine.core.stub_telemetry' has no attribute 'persist_run'` (and `SIDECAR_PATH`).

- [ ] **Step 3: Write minimal implementation**

In `engine/core/stub_telemetry.py`, add `json` and `time` to the imports (they join the existing `atexit`, `os`, `sys`, `collections.Counter`):

```python
import atexit
import json
import os
import sys
import time
from collections import Counter
```

Add the sidecar path resolution just after the `ENABLED` line (so the absolute default is captured at import, before GLFW's macOS chdir can move the CWD):

```python
def _default_sidecar_path() -> str:
    configured = os.environ.get("DAUNTLESS_STUB_TELEMETRY_FILE", "")
    if configured:
        return configured
    # Resolve to absolute at import time — the atexit write runs at shutdown,
    # and GLFW's macOS chdir-hijack can move the CWD after init, so a lazily
    # resolved relative path could land in the wrong directory.
    return os.path.abspath("stub_hits.jsonl")


SIDECAR_PATH: str = _default_sidecar_path()
```

Add `persist_run` (near `dump_report`; like `dump_report` it renders current state and does not itself check `ENABLED` — the enable gate lives at the `atexit`/`set_enabled` level):

```python
def persist_run(path: str | None = None) -> None:
    """Append one JSON line describing this run's counters to the sidecar.

    Never raises — a bad path / full disk / permission error is swallowed so
    persistence can never crash the game. The (owner, attr) pair is encoded as
    a tab-separated key so a dotted breadcrumb attr stays unambiguous."""
    if path is None:
        path = SIDECAR_PATH
    try:
        record = {
            "t": time.time(),
            "attr_hits": {
                ("%s\t%s" % (owner, attr)): count
                for (owner, attr), count in _attr_hits.items()
            },
            "bool_sites": dict(_bool_sites),
        }
        line = json.dumps(record)
        with open(path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
```

Extend `_atexit_dump` to also persist (persist after the report; `persist_run` has its own guard):

```python
def _atexit_dump() -> None:
    if _attr_hits or _bool_sites:
        try:
            dump_report()
        except Exception:
            pass
        persist_run()
```

In `.gitignore`, add the sidecar (append a line):

```
stub_hits.jsonl
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_telemetry_persist.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Confirm Step 0 tests still pass**

Run: `uv run pytest tests/unit/test_stub_telemetry.py tests/unit/test_stub_telemetry_wiring.py tests/unit/test_stub_telemetry_bool.py tests/unit/test_stub_telemetry_report.py -v`
Expected: PASS (15 tests) — the collaborator changed but existing behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/core/stub_telemetry.py .gitignore tests/unit/test_stub_telemetry_persist.py
git commit -m "feat(telemetry): persist per-run stub hits to a gitignored JSONL sidecar"
```

---

### Task 2: Heatmap data layer (load + merge + saturation)

**Files:**
- Create: `tools/stub_heatmap.py`
- Test: `tests/unit/test_stub_heatmap.py`

**Interfaces:**
- Consumes: nothing (stdlib only). Reads sidecar lines in the format Task 1 writes.
- Produces (pure functions):
  - `load_runs(path: str) -> tuple[list[dict], int]` — `(runs, skipped)`. Missing file → `([], 0)`. Skips blank and malformed lines, counting the malformed ones.
  - `merge(runs: list[dict]) -> dict` — `{"M": int, "attr": {key: {"total": int, "runs_seen": int}}, "bool": {key: {"total": int, "runs_seen": int}}}`.
  - `saturation(runs: list[dict]) -> list[int]` — new-`attr_hits`-pairs introduced by each run, in order.
  - `saturation_verdict(series: list[int], window: int = 3) -> str` — plain-English plateau assessment.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_heatmap.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_heatmap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.stub_heatmap'`.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/stub_heatmap.py
"""Merge accumulated stub-telemetry runs (stub_hits.jsonl) into a ranked,
coverage-aware heatmap. Offline, deterministic, run deliberately — see
docs/superpowers/specs/2026-07-10-stub-telemetry-accumulation-design.md.

This is observation only: it consumes what the game appended and never touches
the game or the (future) stubs_known.txt ledger."""

from __future__ import annotations

import json
from collections import Counter


def load_runs(path: str) -> "tuple[list, int]":
    """Return (runs, skipped). Missing file -> ([], 0). Blank lines ignored;
    lines that don't parse to a dict with 'attr_hits' are skipped and counted."""
    try:
        with open(path) as f:
            raw = f.read().splitlines()
    except FileNotFoundError:
        return [], 0
    runs = []
    skipped = 0
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            skipped += 1
            continue
        if not isinstance(rec, dict) or "attr_hits" not in rec:
            skipped += 1
            continue
        runs.append(rec)
    return runs, skipped


def merge(runs: "list") -> dict:
    """Sum hit counts and count per-key coverage across runs."""
    attr_total, attr_runs = Counter(), Counter()
    bool_total, bool_runs = Counter(), Counter()
    for rec in runs:
        for k, c in (rec.get("attr_hits") or {}).items():
            attr_total[k] += c
            attr_runs[k] += 1
        for k, c in (rec.get("bool_sites") or {}).items():
            bool_total[k] += c
            bool_runs[k] += 1
    return {
        "M": len(runs),
        "attr": {k: {"total": attr_total[k], "runs_seen": attr_runs[k]} for k in attr_total},
        "bool": {k: {"total": bool_total[k], "runs_seen": bool_runs[k]} for k in bool_total},
    }


def saturation(runs: "list") -> "list":
    """New attr_hits pairs introduced by each run, in append order."""
    seen = set()
    series = []
    for rec in runs:
        keys = set((rec.get("attr_hits") or {}).keys())
        series.append(len(keys - seen))
        seen |= keys
    return series


def saturation_verdict(series: "list", window: int = 3) -> str:
    """Plain-English plateau assessment for the 'ready to baseline?' signal."""
    if not series:
        return "no runs accumulated"
    tail = series[-window:]
    if len(series) >= window and all(n == 0 for n in tail):
        return "coverage appears SATURATED (last %d runs introduced no new stubs)" % len(tail)
    return "coverage NOT yet saturated (last run introduced %d new stubs)" % series[-1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_heatmap.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/stub_heatmap.py tests/unit/test_stub_heatmap.py
git commit -m "feat(telemetry): stub-heatmap data layer (load/merge/coverage/saturation)"
```

---

### Task 3: Heatmap rendering + CLI

**Files:**
- Modify: `tools/stub_heatmap.py` (add `render`, `_date_range`, `main`)
- Test: `tests/unit/test_stub_heatmap_render.py`

**Interfaces:**
- Consumes: `load_runs`, `merge`, `saturation`, `saturation_verdict` (Task 2).
- Produces:
  - `_date_range(runs: list[dict]) -> tuple[float, float] | None` — min/max of the `t` fields present, or `None` if none.
  - `render(merged: dict, series: list[int], skipped: int, date_range) -> str` — deterministic markdown. No `now()`; date range formatted from the passed `t` values via `time.gmtime`.
  - `main(argv=None) -> int` — CLI: `--sidecar` (default `stub_hits.jsonl`), `--out` (default `docs/stub_heatmap.md`). No runs → prints a notice and writes nothing.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_heatmap_render.py -v`
Expected: FAIL — `AttributeError: module 'tools.stub_heatmap' has no attribute 'render'`.

- [ ] **Step 3: Write minimal implementation**

Add to the top of `tools/stub_heatmap.py` imports:

```python
import argparse
import time
```

Append these functions to `tools/stub_heatmap.py`:

```python
def _date_range(runs: "list"):
    ts = [r["t"] for r in runs if isinstance(r.get("t"), (int, float))]
    if not ts:
        return None
    return (min(ts), max(ts))


def _fmt_ts(t: float) -> str:
    # Deterministic given t (UTC); never uses the current wall clock.
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _sorted_items(section: dict):
    # count descending, then key ascending for stable, deterministic ties
    return sorted(section.items(), key=lambda kv: (-kv[1]["total"], kv[0]))


def render(merged: dict, series: "list", skipped: int, date_range) -> str:
    M = merged["M"]
    lines = []
    lines.append("# Stub Telemetry Heatmap")
    lines.append("")
    run_word = "run" if M == 1 else "runs"
    header = "Accumulated from **%d %s**" % (M, run_word)
    if date_range is not None:
        header += " (%s .. %s)" % (_fmt_ts(date_range[0]), _fmt_ts(date_range[1]))
    header += ". Distinct stubs: %d." % len(merged["attr"])
    if skipped:
        header += " Skipped %d malformed line(s)." % skipped
    lines.append(header)
    lines.append("")
    lines.append("_Observation only — the stubs_known.txt ledger (Piece 2) is separate._")
    lines.append("")
    lines.append("## Coverage saturation")
    lines.append("")
    lines.append("New stubs introduced per run (append order): %s" % (series or "-"))
    lines.append("")
    lines.append("**%s**" % saturation_verdict(series))
    lines.append("")
    lines.append("## Unimplemented-attribute roadmap")
    lines.append("")
    lines.append("| rank | owner.attr | total hits | coverage |")
    lines.append("|---|---|---|---|")
    for i, (key, v) in enumerate(_sorted_items(merged["attr"]), 1):
        lines.append("| %d | %s | %d | %d/%d |"
                     % (i, key.replace("\t", ".", 1), v["total"], v["runs_seen"], M))
    lines.append("")
    lines.append("## Boolean-test call sites (truthiness risk)")
    lines.append("")
    lines.append("| rank | file:line | total hits | coverage |")
    lines.append("|---|---|---|---|")
    for i, (key, v) in enumerate(_sorted_items(merged["bool"]), 1):
        lines.append("| %d | %s | %d | %d/%d |" % (i, key, v["total"], v["runs_seen"], M))
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Merge stub_hits.jsonl into a heatmap.")
    p.add_argument("--sidecar", default="stub_hits.jsonl")
    p.add_argument("--out", default="docs/stub_heatmap.md")
    args = p.parse_args(argv)
    runs, skipped = load_runs(args.sidecar)
    if not runs:
        print("no runs accumulated yet (sidecar: %s)" % args.sidecar)
        return 0
    merged = merge(runs)
    text = render(merged, saturation(runs), skipped, _date_range(runs))
    with open(args.out, "w") as f:
        f.write(text)
    print("wrote %s (%d runs, %d distinct stubs)" % (args.out, merged["M"], len(merged["attr"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_heatmap_render.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 (no failure outside `tests/known_failures.txt`, which is empty). All changes are off-by-default (game) or offline (tools), so nothing that runs by default changed behavior.

- [ ] **Step 6: Commit**

```bash
git add tools/stub_heatmap.py tests/unit/test_stub_heatmap_render.py
git commit -m "feat(telemetry): stub-heatmap rendering + CLI (deterministic docs/stub_heatmap.md)"
```

---

## Self-Review

**1. Spec coverage.** (a) game-side persistence extending the Step 0 collector → Task 1; (b) gitignored JSONL sidecar with the tab-keyed schema + absolute-path default (GLFW chdir) → Task 1; (c) merge + per-pair coverage → Task 2; (d) saturation signal → Task 2; (e) deterministic committed heatmap, date range from data not `now()` → Task 3 (`render`, `_date_range`, `test_render_has_no_wallclock_now`); (f) malformed-line tolerance → Task 2 (`test_load_runs_skips_and_counts_malformed`); (g) off-by-default / never-crash → Global Constraints + Task 1 tests; (h) no game run needed for tests → all tests use temp paths / in-memory records. Deferred items (in-game toggle, auto-regeneration, pruning, the ledger) are correctly absent. **Note:** the plan does NOT create/commit a populated `docs/stub_heatmap.md` — that file is generated later from real accumulation runs; shipping an empty placeholder would be noise (this matches the spec's "generated on demand").

**2. Placeholder scan.** No TBD/TODO; every code step is complete; no "similar to Task N"; all referenced names (`persist_run`, `SIDECAR_PATH`, `load_runs`, `merge`, `saturation`, `saturation_verdict`, `render`, `_date_range`, `main`) are defined in the task that introduces them.

**3. Type consistency.** `merge` returns `{"M", "attr", "bool"}` with per-key `{"total", "runs_seen"}` in Task 2 and is consumed with those exact keys by `render` in Task 3. `load_runs` returns `(runs, skipped)` used consistently. `saturation` returns `list[int]`, consumed by `render`/`saturation_verdict`. The sidecar schema written by `persist_run` (Task 1) — `{"t", "attr_hits": {"owner\tattr": n}, "bool_sites": {"file:line": n}}` — is exactly what `load_runs`/`merge` (Task 2) read.

**Note for the executor:** confirm the exact current text in `engine/core/stub_telemetry.py` before editing (match on the code shown, not line numbers). `tools/__init__.py` already exists, so `from tools import stub_heatmap` imports cleanly.
