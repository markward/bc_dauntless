"""An opt-in cProfile window over whole frames (phase 6 measurement).

The frame profiler's scopes are for phase seams; it says never to put one in
a per-ship or per-projectile loop. To split AI, subsystems and combat by the
class and function doing the work, this runs Python's own deterministic
profiler for a window of frames and dumps pstats:

    DAUNTLESS_PROFILE_PY=<path>            turn it on; pstats written to <path>
    DAUNTLESS_PROFILE_PY_FRAMES=start:count the window (default 600:600)

cProfile inflates call-heavy code (roughly 1.5-3x), so read the RELATIVE
split, never a frame time, from a run with it on. Off, the per-frame cost is
one attribute test.
"""
from __future__ import annotations

import cProfile
import os
import sys

_DEFAULT_START = 600
_DEFAULT_COUNT = 600


class Window:
    def __init__(self, path: str, start: int, count: int):
        self.path = path
        self.start = start
        self.count = count
        self.active = False
        self._frame = 0
        self._prof: cProfile.Profile | None = None
        self._done = False

    @classmethod
    def from_env(cls) -> "Window | None":
        path = os.environ.get("DAUNTLESS_PROFILE_PY")
        if not path:
            return None
        start, count = _DEFAULT_START, _DEFAULT_COUNT
        spec = os.environ.get("DAUNTLESS_PROFILE_PY_FRAMES")
        if spec:
            a, _, b = spec.partition(":")
            start, count = int(a), int(b)
        return cls(path, start, count)

    def frame_tick(self) -> None:
        """Call once at the START of every frame."""
        if self._done:
            return
        if self._frame == self.start:
            self._prof = cProfile.Profile()
            self._prof.enable()
            self.active = True
        elif self._frame == self.start + self.count and self._prof is not None:
            self._prof.disable()
            self.active = False
            self._done = True
            try:
                self._prof.dump_stats(self.path)
                print("[py-profile] %d frames -> %s" % (self.count, self.path),
                      file=sys.stderr)
            except OSError as exc:
                from engine import paths
                paths.report_write_failure(self.path, exc)
            self._prof = None
        self._frame += 1
