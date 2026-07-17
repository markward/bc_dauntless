"""EngPowerCtrl/EngPowerDisplay support widgets — state-holding, render-free.
The CEF Engineering panel snapshots live subsystem state directly; these
exist so Bridge/PowerDisplay.py runs unmodified."""
from engine.appc.tg_ui.widgets import TGPane


class STNumericBar(TGPane):
    def __init__(self):
        super().__init__()
        self._value = 0.0
        self._lo, self._hi = 0.0, 1.0
        self._color = None

    def SetValue(self, v) -> None:       self._value = float(v)
    def GetValue(self) -> float:         return self._value
    def SetRange(self, lo, hi) -> None:  self._lo, self._hi = float(lo), float(hi)
    def SetColor(self, c) -> None:       self._color = c


class STFillGauge(TGPane):
    def __init__(self, kind: int = 0):
        super().__init__()
        self._kind = int(kind)
        self._fill = 0.0
        self._empty_color = None
        self._fill_color = None

    def SetFillFraction(self, f) -> None:  self._fill = float(f)
    def GetFillFraction(self) -> float:    return self._fill
    def SetEmptyColor(self, c) -> None:    self._empty_color = c
    def SetFillColor(self, c) -> None:     self._fill_color = c


# ── Singletons ────────────────────────────────────────────────────────────────

_power_ctrl_singleton = None
_power_display_singleton = None

# Host-registered signal: True while the Engineering crew menu is the open
# top-level station menu.  EngPowerDisplay.IsCompletelyVisible() consults it so
# BC's per-tick AdjustPower runs only while the display is on screen.  Module
# level (not per-instance) because the SDK recreates the display singleton on
# every bridge load, while the host registers this once at boot.
_engineering_open_check = None


def set_engineering_open_check(fn) -> None:
    """Register (or clear with None) the engineering-menu-open predicate."""
    global _engineering_open_check
    _engineering_open_check = fn


def _reset_eng_power_singletons() -> None:
    global _power_ctrl_singleton, _power_display_singleton
    _power_ctrl_singleton = None
    _power_display_singleton = None
    # NOTE: _engineering_open_check is intentionally NOT reset here — it is a
    # boot-time host registration that must survive bridge reloads.


# ── EngPowerCtrl ──────────────────────────────────────────────────────────────

class EngPowerCtrl(TGPane):
    def __init__(self, width: float = 0.0):
        super().__init__(width, 0.0)
        self._bars: dict = {}      # id(subsystem) -> (subsystem, STNumericBar)

    def GetBarForSubsystem(self, subsystem):
        if subsystem is None:
            return None
        key = id(subsystem)
        entry = self._bars.get(key)
        if entry is None:
            bar = STNumericBar()
            bar.SetRange(0.0, 1.25)
            self._bars[key] = (subsystem, bar)
            return bar
        return entry[1]

    def Refresh(self) -> None:
        for subsystem, bar in self._bars.values():
            bar.SetValue(subsystem.GetPowerPercentageWanted())


def EngPowerCtrl_Create(width: float = 0.0) -> "EngPowerCtrl":
    global _power_ctrl_singleton
    _power_ctrl_singleton = EngPowerCtrl(width)
    return _power_ctrl_singleton


def EngPowerCtrl_GetPowerCtrl() -> "EngPowerCtrl | None":
    return _power_ctrl_singleton


def EngPowerCtrl_Cast(obj) -> "EngPowerCtrl | None":
    return obj if isinstance(obj, EngPowerCtrl) else None


# ── EngPowerDisplay ───────────────────────────────────────────────────────────

class EngPowerDisplay(TGPane):
    MAIN = 0
    BACKUP = 1
    WARP_CORE = 2

    def __init__(self, width: float = 0.0, height: float = 0.0):
        super().__init__(width, height)
        # In BC the display is always mounted inside a window, so
        # PowerDisplay.Init's final `GetParent().Resize(...)` (SDK line 275)
        # never sees None. Headless has no window tree; give it a benign
        # container pane so Init runs to completion instead of raising there
        # (that raise aborted every ET_SET_PLAYER re-init and left the QB helm
        # menu half-wired — the 2026-07 power-branch regression).
        self._parent_pane = TGPane()
        self._parent_pane.AddChild(self, 0.0, 0.0, 0)

    def CreateBatteryGauge(self, which) -> "STFillGauge":
        return STFillGauge(which)

    def GetParent(self):
        return self._parent_pane

    def GetConceptualParent(self):
        return None

    def IsCompletelyVisible(self) -> int:
        """On screen iff the Engineering crew menu is open.

        The engineering-open signal encodes this widget's ancestor context
        (the display lives inside the Engineering pane, visible only when that
        menu is up), so it stands in for the base chain-walk.  Falls back to
        TGPane's own-visibility walk when no host check is registered (bare
        unit contexts).
        """
        if _engineering_open_check is not None:
            return 1 if _engineering_open_check() else 0
        return super().IsCompletelyVisible()


def EngPowerDisplay_Create(width: float = 0.0, height: float = 0.0) -> "EngPowerDisplay":
    global _power_display_singleton
    _power_display_singleton = EngPowerDisplay(width, height)
    try:
        import Bridge.PowerDisplay
        Bridge.PowerDisplay.Init(_power_display_singleton)
    except Exception as exc:
        # SDK not importable in bare-unit contexts; the ET_SET_PLAYER re-init
        # path covers the live game. Never let UI construction kill a boot.
        try:
            from engine import dev_mode
            dev_mode.log_swallowed("EngPowerDisplay_Create Bridge.PowerDisplay.Init", exc)
        except Exception:
            pass
    return _power_display_singleton


def EngPowerDisplay_GetPowerDisplay() -> "EngPowerDisplay | None":
    return _power_display_singleton


def EngPowerDisplay_Cast(obj) -> "EngPowerDisplay | None":
    return obj if isinstance(obj, EngPowerDisplay) else None
