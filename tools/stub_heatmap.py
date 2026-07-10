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
