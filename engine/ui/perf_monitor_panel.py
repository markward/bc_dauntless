"""Performance monitor overlay — developer-only readout in the top-right corner.

Shows the render resolution (framebuffer size in physical pixels, which is what
the scene draws at -- there is no separate render scale) plus FPS and average
frame time from ``engine.dev_perf_monitor.FrameRateMeter``. Switched on from
Developer Options → Diagnostics → "Performance Monitor"; the flag lives in
``engine.dev_perf_monitor``.

The host loop calls ``tick(wall_dt)`` every frame, which feeds the meter and
mirrors the flag onto ``visible`` (the registry skips hidden panels, so the
flag cannot be read from render_payload alone). Polled at 4 Hz: the meter only
publishes twice a second, and the readout must not itself cost a frame.

Dev-mode only — constructed in host_loop.py inside
``if dev_mode.is_enabled():``.

Spec: docs/superpowers/specs/2026-10-20-dev-perf-monitor-design.md
"""
from __future__ import annotations

import json
from typing import Callable, Optional, Tuple

from engine import dev_perf_monitor
from engine.ui.panel import Panel


def _framebuffer_size() -> Tuple[int, int]:
    """Imported lazily: host_io reaches the native extension, and this panel
    is constructed in tests that never build it."""
    from engine import host_io
    return host_io.framebuffer_size()


class PerfMonitorPanel(Panel):
    def __init__(self, size_fn: Optional[Callable[[], Tuple[int, int]]] = None) -> None:
        super().__init__()
        self._size_fn = size_fn or _framebuffer_size
        self._meter = dev_perf_monitor.FrameRateMeter()
        self._visible = False
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "perf-monitor"

    @property
    def poll_interval_s(self) -> float:
        return 0.25

    def tick(self, wall_dt: float) -> None:
        self._meter.record(wall_dt)
        self.visible = dev_perf_monitor.enabled()

    def _size(self) -> Tuple[int, int]:
        try:
            w, h = self._size_fn()
            return int(w), int(h)
        except Exception:
            return 0, 0

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            snapshot: tuple = (False,)
            payload: dict = {"visible": False}
        else:
            w, h = self._size()
            fps = None if self._meter.fps is None else int(round(self._meter.fps))
            frame_ms = (None if self._meter.frame_ms is None
                        else round(self._meter.frame_ms, 1))
            snapshot = (True, w, h, fps, frame_ms)
            payload = {"visible": True, "width": w, "height": h,
                       "fps": fps, "frame_ms": frame_ms}
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        return "setPerfMonitor(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
        super().invalidate()
