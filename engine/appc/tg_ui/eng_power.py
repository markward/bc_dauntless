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
