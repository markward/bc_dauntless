"""Unattended dev runs: destroy a named object once the cutscenes are over,
then optionally quit. Developer mode only.

Exists so a perf baseline that needs one keypress can run with nobody at the
keyboard: B1 (docs/engine/perf-register.md) is E1M2 with the Haven
"Facility" destroyed after the opening cutscene. The destroy uses the same
death path as the `]` dev key (engine/dev_keybindings.py).

    DAUNTLESS_DEV_DESTROY=<object name>   e.g. Facility
    DAUNTLESS_DEV_DESTROY_DELAY_S=<s>     seconds clear of any cutscene before
                                          the destroy (default 10); a new
                                          cutscene restarts the wait
    DAUNTLESS_DEV_QUIT_AFTER_S=<s>        quit this long after the destroy
                                          (default: never)
    DAUNTLESS_DEV_VIEW=exterior           force the exterior (tactical) view
                                          at the start of each cutscene-free
                                          stretch, as a player watching the
                                          destroy would
    DAUNTLESS_DEV_SCREENSHOT=<path.png>   write one frame as a PNG this long
    DAUNTLESS_DEV_SCREENSHOT_AFTER_S=<s>  clear of cutscenes (default 5), so
                                          before/after builds picture the
                                          same scripted moment

Time is the host loop's player dt, so it stops while paused. Each event is
printed as a `[dev-scripted]` line, which also marks it in a profiler log.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

DESTROY_ENV = "DAUNTLESS_DEV_DESTROY"
DELAY_ENV = "DAUNTLESS_DEV_DESTROY_DELAY_S"
QUIT_ENV = "DAUNTLESS_DEV_QUIT_AFTER_S"
VIEW_ENV = "DAUNTLESS_DEV_VIEW"
SCREENSHOT_ENV = "DAUNTLESS_DEV_SCREENSHOT"
SCREENSHOT_AFTER_ENV = "DAUNTLESS_DEV_SCREENSHOT_AFTER_S"
DEFAULT_DELAY_S = 10.0
DEFAULT_SCREENSHOT_AFTER_S = 5.0


def _float_or(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ScriptedRun:
    def __init__(self, target: str, delay_s: float = DEFAULT_DELAY_S,
                 quit_after_s: Optional[float] = None,
                 view: Optional[str] = None,
                 screenshot_path: Optional[str] = None,
                 screenshot_after_s: float = DEFAULT_SCREENSHOT_AFTER_S) -> None:
        self.target = target
        self.view = view
        self.screenshot_path = screenshot_path
        self.screenshot_after_s = screenshot_after_s
        self._shot = False
        self._view_applied = False
        self.delay_s = delay_s
        self.quit_after_s = quit_after_s
        self._clear_s = 0.0
        self._in_cutscene = False
        self._destroyed = False
        self._since_destroy_s = 0.0
        self._quit = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str],
                 developer: bool) -> Optional["ScriptedRun"]:
        target = environ.get(DESTROY_ENV, "").strip()
        if not developer or not target:
            return None
        quit_raw = environ.get(QUIT_ENV, "").strip()
        view = environ.get(VIEW_ENV, "").strip() or None
        shot = environ.get(SCREENSHOT_ENV, "").strip() or None
        return cls(target,
                   delay_s=_float_or(environ.get(DELAY_ENV), DEFAULT_DELAY_S),
                   quit_after_s=_float_or(quit_raw, None) if quit_raw else None,
                   view=view, screenshot_path=shot,
                   screenshot_after_s=_float_or(environ.get(SCREENSHOT_AFTER_ENV),
                                                DEFAULT_SCREENSHOT_AFTER_S))

    def tick(self, dt: float, cutscene_active: bool,
             destroy: Callable[[str], bool],
             log: Callable[[str], None] = lambda _line: None,
             force_view: Optional[Callable[[str], None]] = None,
             screenshot: Optional[Callable[[str], None]] = None) -> bool:
        """Advance by `dt` seconds. `destroy(name)` returns True once it found
        and destroyed the object. Returns True on the tick the run should quit."""
        if self._quit:
            return True
        if cutscene_active != self._in_cutscene:
            self._in_cutscene = cutscene_active
            log("[dev-scripted] cutscene %s" % ("start" if cutscene_active
                                                else "end"))
            if cutscene_active:
                self._view_applied = False
        if (self.view and not cutscene_active and not self._view_applied
                and force_view is not None):
            # Once per cutscene-free stretch: a cutscene may return the camera
            # to the bridge, but every frame would fight the mission's own
            # camera changes.
            self._view_applied = True
            force_view(self.view)
            log("[dev-scripted] view %s" % self.view)
        if self._destroyed:
            if self.quit_after_s is None:
                return False
            self._since_destroy_s += dt
            if self._since_destroy_s >= self.quit_after_s:
                self._quit = True
                log("[dev-scripted] quit %.1f s after the destroy"
                    % self._since_destroy_s)
                return True
            return False
        if cutscene_active:
            self._clear_s = 0.0
            return False
        self._clear_s += dt
        if (self.screenshot_path and not self._shot and screenshot is not None
                and self._clear_s >= self.screenshot_after_s):
            self._shot = True
            screenshot(self.screenshot_path)
            log("[dev-scripted] screenshot %s after %.1f s clear of cutscenes"
                % (self.screenshot_path, self._clear_s))
        if self._clear_s >= self.delay_s and destroy(self.target):
            self._destroyed = True
            log("[dev-scripted] destroyed %s after %.1f s clear of cutscenes"
                % (self.target, self._clear_s))
        return False


# ── Quit requests from a dev mission ────────────────────────────────────────
# A dev mission knows when its run is over (felix_destroy: a few seconds after
# the first ship death) but only the host loop can leave the frame loop. The
# mission calls request_quit; the host loop calls tick_quit_request every
# frame and breaks on True. The earliest deadline wins, so a time cap set at
# mission start never holds back a shorter post-death quit.

_quit_remaining_s: Optional[float] = None
_quit_reason = ""


def request_quit(after_s: float, reason: str) -> None:
    global _quit_remaining_s, _quit_reason
    after_s = max(0.0, float(after_s))
    if _quit_remaining_s is None or after_s < _quit_remaining_s:
        _quit_remaining_s = after_s
        _quit_reason = reason


def pending_quit_s() -> Optional[float]:
    """Seconds until the requested quit, or None when none is pending."""
    return _quit_remaining_s


def clear_quit_request() -> None:
    global _quit_remaining_s, _quit_reason
    _quit_remaining_s = None
    _quit_reason = ""


def tick_quit_request(dt: float,
                      log: Callable[[str], None] = lambda _line: None) -> bool:
    """Advance a pending quit by `dt`. True on the tick it falls due."""
    global _quit_remaining_s
    if _quit_remaining_s is None:
        return False
    _quit_remaining_s -= dt
    if _quit_remaining_s > 1e-9:
        return False
    log("[dev-scripted] quit: %s" % (_quit_reason or "requested"))
    clear_quit_request()
    return True
