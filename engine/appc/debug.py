"""CPyDebug + TGProfilingInfo — engine-side debug helpers.

SDK call sites:
* ``debug = App.CPyDebug(__name__).Print`` — module-scoped logger pattern,
  used by Bridge/PowerDisplay.py, AI/Compound/BasicAttack.py and
  diagnostic scripts (SSDiag.py).
* ``iTimingId = App.TGProfilingInfo_StartTiming("name")`` /
  ``App.TGProfilingInfo_StopTiming(iTimingId)`` — paired around hot
  per-frame paths in Effects.py to time particle-effect creation.
* ``App.TGProfilingInfo_EnableProfiling()`` — toggles the global profiler
  (commented out in Autoexec.py — opt-in by default).

Phase 1 model:
* CPyDebug routes through Python's stdlib ``logging`` so output can be
  captured / suppressed by tests via standard logging configuration.
  Default level is WARNING — Print() emits at INFO so it stays out of
  default test output.
* TGProfilingInfo records start times in a per-process registry; Stop
  returns the elapsed seconds (so callers that capture the return can
  log it).  Profiling is on by default in headless mode — the cost is
  negligible and tests want timing visibility.
"""

import logging
import time as _time

import engine.dev_mode as dev_mode


_log = logging.getLogger("open_stbc.cpy_debug")


class CPyDebug:
    """Module-scoped debug logger."""
    def __init__(self, name: str = ""):
        self._name = str(name) if name else "open_stbc.cpy_debug"
        self._logger = logging.getLogger(self._name) if name else _log

    def Print(self, message) -> None:
        self._logger.info("%s", str(message))

    def GetName(self) -> str:
        return self._name


# ── TGProfilingInfo ─────────────────────────────────────────────────────────

_profiling_enabled: bool = True
_active_timings: dict = {}        # int ID -> (name, start_time)
_completed_timings: dict = {}     # name -> total elapsed seconds (sum across calls)
_next_timing_id: int = 1


class TGProfilingInfo:
    """RAII timing scope.

    SDK pattern (MissionLib.py:4776, Bridge/HelmMenuHandlers.py:2420,
    Tactical/Interface/TacticalControlWindow.py):

        kProfiling = App.TGProfilingInfo("MissionLib.PreloadSequenceLines")
        ...do work...
        # kProfiling falls out of scope; __del__ stops the timing

    Construction marks timing-start; the instance going out of scope (or
    being explicitly garbage-collected) marks timing-stop.  Functionally
    equivalent to wrapping the same code in a Start/Stop call pair around
    the whole function body.
    """
    def __init__(self, name: str = ""):
        self._name = str(name) if name else ""
        self._timing_id = TGProfilingInfo_StartTiming(self._name) if self._name else 0

    def __del__(self):
        if self._timing_id:
            try:
                TGProfilingInfo_StopTiming(self._timing_id)
            except Exception as _e:
                dev_mode.log_swallowed("stop profiling timer (__del__)", _e)

    def Stop(self) -> float:
        """Explicit stop — useful when the caller wants the elapsed value."""
        if self._timing_id:
            elapsed = TGProfilingInfo_StopTiming(self._timing_id)
            self._timing_id = 0
            return elapsed
        return 0.0

    def GetName(self) -> str:
        return self._name


def TGProfilingInfo_EnableProfiling() -> None:
    global _profiling_enabled
    _profiling_enabled = True


def TGProfilingInfo_DisableProfiling() -> None:
    global _profiling_enabled
    _profiling_enabled = False


def TGProfilingInfo_IsProfilingEnabled() -> int:
    return 1 if _profiling_enabled else 0


def TGProfilingInfo_StartTiming(name: str) -> int:
    """Begin a named timing.  Returns an integer ID for StopTiming.

    SDK pattern (Effects.py:28):
        iTimingId = App.TGProfilingInfo_StartTiming("Effects::CreateExplosionPuffHigh")
        ...do work...
        App.TGProfilingInfo_StopTiming(iTimingId)

    When profiling is disabled, returns 0 — StopTiming(0) is a no-op.
    """
    global _next_timing_id
    if not _profiling_enabled:
        return 0
    timing_id = _next_timing_id
    _next_timing_id += 1
    _active_timings[timing_id] = (str(name), _time.perf_counter())
    return timing_id


def TGProfilingInfo_StopTiming(timing_id: int) -> float:
    """Stop a previously-started timing and accumulate elapsed seconds.

    Returns the elapsed time in seconds (0.0 if the ID is unknown or 0).
    """
    if timing_id == 0 or timing_id not in _active_timings:
        return 0.0
    name, start = _active_timings.pop(int(timing_id))
    elapsed = _time.perf_counter() - start
    _completed_timings[name] = _completed_timings.get(name, 0.0) + elapsed
    return elapsed


def TGProfilingInfo_GetTotalTime(name: str) -> float:
    """Return the cumulative elapsed seconds for a named timing.

    Convenience accessor — the SDK reports timings via a separate UI; tests
    can read accumulated totals here.
    """
    return _completed_timings.get(str(name), 0.0)


def TGProfilingInfo_ResetTimings() -> None:
    _active_timings.clear()
    _completed_timings.clear()
