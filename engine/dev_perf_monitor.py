"""Developer-only performance monitor: the on/off flag and the frame-rate meter.

Developer Options → Diagnostics → "Performance Monitor" writes the flag;
``engine.ui.perf_monitor_panel.PerfMonitorPanel`` reads it and draws the
top-right overlay (render resolution, FPS, frame time). Neither side imports
the other -- this module is the seam, the same shape as
``engine.dev_combat_cheats``.

``enabled()`` ANDs the flag with ``dev_mode.is_enabled()`` so the overlay can
never appear in a production run. Off by default, not persisted.

The meter measures WALL-clock frames (the host loop's ``_wall_dt``), not sim
ticks: it is what the player sees, and it keeps counting while paused.

Spec: docs/superpowers/specs/2026-10-20-dev-perf-monitor-design.md
"""
from typing import Optional

from engine import dev_mode

_enabled: bool = False


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def enabled() -> bool:
    return _enabled and dev_mode.is_enabled()


def reset() -> None:
    """Clear the flag. Used by tests; not wired to runtime teardown."""
    global _enabled
    _enabled = False


class FrameRateMeter:
    """Average frame rate over fixed windows of wall time.

    Publishes once per window rather than as a running average, so a slow
    stretch shows within one window instead of being diluted by history, and
    the number holds still long enough to read. ``fps``/``frame_ms`` are None
    until the first window closes.
    """

    def __init__(self, window_s: float = 0.5) -> None:
        self._window_s = window_s
        self._frames = 0
        self._elapsed = 0.0
        self.fps: Optional[float] = None
        self.frame_ms: Optional[float] = None

    def record(self, wall_dt: float) -> None:
        if wall_dt <= 0.0:
            return
        self._frames += 1
        self._elapsed += wall_dt
        # Small tolerance: 30 x (1/60) sums to a hair under 0.5 in floating
        # point, and a window that closes one frame late reads as 59.x fps.
        if self._elapsed >= self._window_s - 1e-9:
            self.fps = self._frames / self._elapsed
            self.frame_ms = self._elapsed * 1000.0 / self._frames
            self._frames = 0
            self._elapsed = 0.0
