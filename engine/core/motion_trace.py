"""Per-frame player-motion trace, for diagnosing judder on high-refresh
displays (the player looks like it moves only every other frame while an AI
order or a cutscene flies it).

    DAUNTLESS_MOTION_TRACE=<path>    enable from boot and append CSV rows here

One row per render frame: the frame's wall-clock start and end (end is after
r.frame(), so it includes the present), the sim ticks it ran, the
interpolation alpha, which pipeline drew the player, the player's live pose,
the pose it was drawn at, and the camera eye/target. Off by default; when off
the host loop pays one bool check per frame. Never raises.
"""

import os
import time

TRACE_ENV = "DAUNTLESS_MOTION_TRACE"
FLUSH_EVERY = 240

_HEADER = ("frame,t_start,t_end,frame_dt,ticks,alpha,interp,ai,cutscene,"
           "handover,live_x,live_y,live_z,drawn_x,drawn_y,drawn_z,"
           "eye_x,eye_y,eye_z,tgt_x,tgt_y,tgt_z")

_path = None
_rows = []
_frame = 0


def configure_from_env() -> bool:
    """Start tracing to $DAUNTLESS_MOTION_TRACE. True when enabled."""
    global _path, _rows, _frame
    path = os.environ.get(TRACE_ENV, "").strip()
    if not path:
        return False
    _path = path
    _rows = [_HEADER]
    _frame = 0
    import atexit
    atexit.register(flush)
    print("[motion-trace] writing %s" % _path, flush=True)
    return True


def enabled() -> bool:
    return _path is not None


def _xyz(p):
    if p is None:
        return ("", "", "")
    if hasattr(p, "x"):
        return ("%.6f" % p.x, "%.6f" % p.y, "%.6f" % p.z)
    return ("%.6f" % p[0], "%.6f" % p[1], "%.6f" % p[2])


def record(*, t_start, frame_dt, ticks, alpha, interp, ai, cutscene,
           handover, live, drawn, eye, target) -> None:
    """Append one frame. `live` / `drawn` are positions (TGPoint3 or a
    3-sequence) or None; `eye` / `target` 3-sequences or None."""
    global _frame
    if _path is None:
        return
    try:
        t_end = time.monotonic()
        _rows.append(",".join(
            (str(_frame), "%.6f" % t_start, "%.6f" % t_end,
             "%.6f" % frame_dt, str(int(ticks)), "%.4f" % alpha,
             str(int(bool(interp))), str(int(bool(ai))),
             str(int(bool(cutscene))), str(int(bool(handover))))
            + _xyz(live) + _xyz(drawn) + _xyz(eye) + _xyz(target)))
        _frame += 1
        if len(_rows) >= FLUSH_EVERY:
            flush()
    except Exception as e:
        print("[motion-trace] record failed: %s: %s" % (type(e).__name__, e),
              flush=True)


def flush() -> None:
    global _rows
    if _path is None or not _rows:
        return
    try:
        with open(_path, "a", encoding="ascii") as f:
            f.write("\n".join(_rows) + "\n")
    except Exception as e:
        print("[motion-trace] write failed: %s: %s" % (type(e).__name__, e),
              flush=True)
    _rows = []
