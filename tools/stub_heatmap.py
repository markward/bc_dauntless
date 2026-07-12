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


def _date_range(runs: "list"):
    ts = [r["t"] for r in runs if isinstance(r.get("t"), (int, float))]
    if not ts:
        return None
    return (min(ts), max(ts))


def _fmt_ts(t: float) -> str:
    # Deterministic given t (UTC); never uses the current wall clock.
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


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
    counted; a single bad row never drops the rest. A non-empty
    markedResolvedOn cell (not '—'/'-') that fails to parse as a date (a
    human typo) is also counted as skipped and excluded from the map, rather
    than being silently accepted and misclassified as 'open' downstream."""
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
                            if parse_resolved_date(marked) is None:
                                skipped += 1
                            else:
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
    """One row dict per attr key, classified and carrying its annotation.

    Unions the current merge keys with the annotated (owner, attr) keys, so a
    stub marked resolved that has zero hits in the current sidecar (e.g. after
    stub_hits.jsonl was reset) still gets a synthesized zero-hit row and
    survives regeneration instead of silently dropping out of the file."""
    keys = set(merged["attr"].keys())
    for owner, attr in resolved_map:
        keys.add(owner + "\t" + attr)
    rows = []
    for key in keys:
        owner, _, attr = key.partition("\t")
        marked = resolved_map.get((owner, attr), "")
        v = merged["attr"].get(key)
        if v is None:
            total, runs_seen, ls = 0, 0, None
        else:
            total, runs_seen, ls = v["total"], v["runs_seen"], last_seen.get(key)
        rows.append({
            "owner": owner, "attr": attr,
            "total": total, "runs_seen": runs_seen,
            "last_seen": ls, "marked": marked,
            "status": classify(ls, marked),
        })
    return rows


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
    L += ["_Implemented one? Type the date (`YYYY-MM-DD`) into its `markedResolvedOn`"
          " cell and commit — it moves to Resolved on the next regeneration, and is"
          " flagged again if it is ever hit after that date._", ""]
    L += ["| rank | owner | attr | total hits | coverage | lastSeenOn | markedResolvedOn |",
          "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(openr, 1):
        L.append("| %d | %s | %s | %d | %d/%d | %s | %s |"
                 % (i, r["owner"], r["attr"], r["total"], r["runs_seen"], M,
                    _ls(r["last_seen"]), r["marked"]))
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


if __name__ == "__main__":
    raise SystemExit(main())
