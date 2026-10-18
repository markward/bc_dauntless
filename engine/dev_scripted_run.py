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

Time is the host loop's player dt, so it stops while paused. Each event is
printed as a `[dev-scripted]` line, which also marks it in a profiler log.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

DESTROY_ENV = "DAUNTLESS_DEV_DESTROY"
DELAY_ENV = "DAUNTLESS_DEV_DESTROY_DELAY_S"
QUIT_ENV = "DAUNTLESS_DEV_QUIT_AFTER_S"
VIEW_ENV = "DAUNTLESS_DEV_VIEW"
DEFAULT_DELAY_S = 10.0


def _float_or(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ScriptedRun:
    def __init__(self, target: str, delay_s: float = DEFAULT_DELAY_S,
                 quit_after_s: Optional[float] = None,
                 view: Optional[str] = None) -> None:
        self.target = target
        self.view = view
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
        return cls(target,
                   delay_s=_float_or(environ.get(DELAY_ENV), DEFAULT_DELAY_S),
                   quit_after_s=_float_or(quit_raw, None) if quit_raw else None,
                   view=view)

    def tick(self, dt: float, cutscene_active: bool,
             destroy: Callable[[str], bool],
             log: Callable[[str], None] = lambda _line: None,
             force_view: Optional[Callable[[str], None]] = None) -> bool:
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
        if self._clear_s >= self.delay_s and destroy(self.target):
            self._destroyed = True
            log("[dev-scripted] destroyed %s after %.1f s clear of cutscenes"
                % (self.target, self._clear_s))
        return False
