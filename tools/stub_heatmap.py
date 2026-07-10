"""Merge accumulated stub-telemetry runs (stub_hits.jsonl) into a ranked,
coverage-aware heatmap. Offline, deterministic, run deliberately — see
docs/superpowers/specs/2026-07-10-stub-telemetry-accumulation-design.md.

This is observation only: it consumes what the game appended and never touches
the game or the (future) stubs_known.txt ledger."""

from __future__ import annotations

import argparse
import datetime
import json
import time
from collections import Counter


def load_runs(path: str) -> "tuple[list, int]":
    """Return (runs, skipped). Missing file -> ([], 0). Blank lines ignored;
    lines that don't parse to a dict with a dict-valued 'attr_hits' are
    skipped and counted."""
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
        if not isinstance(rec, dict) or not isinstance(rec.get("attr_hits"), dict):
            skipped += 1
            continue
        runs.append(rec)
    return runs, skipped


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
        header += " Skipped %d malformed line%s." % (skipped, "" if skipped == 1 else "s")
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
