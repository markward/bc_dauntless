"""Summarise a DAUNTLESS_MOTION_TRACE capture (engine/core/motion_trace.py).

    uv run python tools/motion_trace_report.py <trace.csv>

Splits the capture into runs of frames by who drew the player (interpolated
vs live) and, per run, reports frame pacing and how evenly the drawn player
and the camera moved per frame. A ship drawn smoothly moves a distance
proportional to the frame's wall dt; "moves every other frame" shows up as
many frames with near-zero drawn displacement while the live pose is moving,
or a large spread of per-frame speed.
"""
import csv
import math
import statistics
import sys


def _f(row, k):
    v = row[k]
    return float(v) if v != "" else None


def _vec(row, p):
    x = _f(row, p + "_x")
    if x is None:
        return None
    return (x, _f(row, p + "_y"), _f(row, p + "_z"))


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _pct(xs, q):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def _runs(rows):
    """Contiguous runs of frames sharing (interp, ai, cutscene)."""
    out, cur, key = [], [], None
    for r in rows:
        k = (r["interp"], r["ai"], r["cutscene"])
        if k != key and cur:
            out.append((key, cur))
            cur = []
        key = k
        cur.append(r)
    if cur:
        out.append((key, cur))
    return out


def _report_run(key, rows):
    interp, ai, cut = key
    n = len(rows)
    print("\n== %d frames  interp=%s ai=%s cutscene=%s  (frames %s..%s)"
          % (n, interp, ai, cut, rows[0]["frame"], rows[-1]["frame"]))
    dts, durs, ticks = [], [], []
    drawn_speed, live_speed, rel_step = [], [], []
    still_drawn = 0
    still_live = 0
    moving = 0
    for a, b in zip(rows, rows[1:]):
        dt = float(b["t_start"]) - float(a["t_start"])
        dts.append(dt * 1000.0)
        durs.append((float(b["t_end"]) - float(b["t_start"])) * 1000.0)
        ticks.append(int(b["ticks"]))
        da, db = _vec(a, "drawn"), _vec(b, "drawn")
        la, lb = _vec(a, "live"), _vec(b, "live")
        ea, eb = _vec(a, "eye"), _vec(b, "eye")
        if la and lb and dt > 0:
            ls = _dist(la, lb) / dt
            live_speed.append(ls)
        if da and db and dt > 0:
            ds = _dist(da, db) / dt
            drawn_speed.append(ds)
            if la and lb and _dist(la, lb) > 1e-6:
                moving += 1
                if _dist(da, db) < 1e-6:
                    still_drawn += 1
            if la and lb and _dist(la, lb) < 1e-6:
                still_live += 1
            if ea and eb:
                # Ship position relative to the eye: what the viewer sees move.
                rel_step.append(_dist(_sub(db, eb), _sub(da, ea)) / dt)
    if not dts:
        return
    print("  frame dt ms   p5 %.2f  p50 %.2f  p95 %.2f  max %.2f"
          % (_pct(dts, .05), _pct(dts, .5), _pct(dts, .95), max(dts)))
    print("  frame work ms p50 %.2f  p95 %.2f   (start -> after r.frame)"
          % (_pct(durs, .5), _pct(durs, .95)))
    hist = {}
    for t in ticks:
        hist[t] = hist.get(t, 0) + 1
    print("  ticks/frame   %s" % ", ".join(
        "%d:%d" % (k, hist[k]) for k in sorted(hist)))
    seq = "".join(str(min(t, 9)) for t in ticks[:80])
    print("  tick pattern  %s" % seq)
    if drawn_speed:
        m = statistics.mean(drawn_speed)
        sd = statistics.pstdev(drawn_speed)
        print("  drawn speed   mean %.4f GU/s  cv %.3f" % (m, sd / m if m else 0))
    if live_speed:
        m = statistics.mean(live_speed)
        sd = statistics.pstdev(live_speed)
        print("  live speed    mean %.4f GU/s  cv %.3f  (live still %d frames)"
              % (m, sd / m if m else 0, still_live))
    print("  drawn still while live moved: %d of %d frames" % (still_drawn, moving))
    if rel_step:
        m = statistics.mean(rel_step)
        sd = statistics.pstdev(rel_step)
        print("  ship-vs-eye   mean %.4f GU/s  cv %.3f" % (m, sd / m if m else 0))


def main(path):
    with open(path, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["frame"] != "frame"]
    print("%d frames" % len(rows))
    flips = sum(1 for a, b in zip(rows, rows[1:]) if a["interp"] != b["interp"])
    print("interp flips: %d" % flips)
    for key, run in _runs(rows):
        if len(run) >= 30:
            _report_run(key, run)


if __name__ == "__main__":
    main(sys.argv[1])
