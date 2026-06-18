"""TEMPORARY action-sequence diagnostic logging (NOT committed to the branch).

Enabled only when env var DAUNTLESS_SEQ_DEBUG is set. Writes to stderr (visible
in the terminal that launched ./build/dauntless). Used to diagnose why the E1M1
Starbase 12 comm hail does not show Liu after the real-duration timing fix.
Remove this module + its call sites once the bug is understood.
"""
import os
import sys

_ON = bool(os.environ.get("DAUNTLESS_SEQ_DEBUG"))


def _t() -> str:
    try:
        import App
        gt = App.g_kTimerManager.get_time()
        rt = App.g_kRealtimeTimerManager.get_time()
        return "g=%.3f r=%.3f" % (gt, rt)
    except Exception:
        return "g=? r=?"


def log(msg: str) -> None:
    if not _ON:
        return
    try:
        sys.stderr.write("[SEQDBG %s] %s\n" % (_t(), msg))
        sys.stderr.flush()
    except Exception:
        pass
