"""TacticalControlWindow placeholder.

Real BC TCW is a full window with menus / layout / focus.  PR 2a only
needs the event-handler-object surface so TacticalInterfaceHandlers.
RegisterHandlers(pTCW) can install fire-event handlers on it.  Future
PRs will replace this with the real window when the menu system lands.
"""
from engine.appc.events import TGEventHandlerObject


class TacticalControlWindow(TGEventHandlerObject):
    _instance: "TacticalControlWindow | None" = None

    def __init__(self):
        super().__init__()
        self._radar_display = None

    @classmethod
    def GetInstance(cls) -> "TacticalControlWindow":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def CallNextHandler(self, _evt) -> None:
        """SDK handlers call pObject.CallNextHandler(pEvent) for chain
        propagation.  Without a parent window chain we no-op."""
        return None

    # Radar display accessor — SDK TacticalMenuHandlers.CreateRadarDisplay
    # at sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:475 calls
    # pTacticalWindow.SetRadarDisplay(p); RadarDisplay.py:55 calls
    # pTCW.GetRadarDisplay() to get it back.
    def SetRadarDisplay(self, p) -> None:
        self._radar_display = p

    def GetRadarDisplay(self):
        return self._radar_display


import time


# ── SubtitleWindow ──────────────────────────────────────────────────────────
# Singleton main window that hosts mission-objective / cinematic banner text.
# TGCreditAction.Play() calls _add_text(text, duration); the mirror panel
# snapshots (and prunes expired entries) once per tick.
# Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md

class _SubtitleWindow:
    # SM_* constants are duplicated on the exported SubtitleWindow class
    # below — SDK code accesses them as App.SubtitleWindow.SM_TACTICAL.
    _SM_BRIDGE, _SM_TACTICAL, _SM_FELIX, _SM_NONFELIX = 0, 1, 2, 3
    _SM_MAP, _SM_CINEMATIC, _SM_END_CINEMATIC, _SM_SPECIAL_FELIX = 4, 5, 6, 7

    def __init__(self):
        self._id = "subtitle-0"
        self._visible = False
        self._mode = self._SM_TACTICAL
        self._active_texts: list[tuple[str, float]] = []

    def SetOn(self) -> None:    self._visible = True
    def SetOff(self) -> None:   self._visible = False
    def SetVisible(self) -> None: self._visible = True  # SDK alias (MissionLib.TextBanner)
    def IsOn(self) -> bool:     return self._visible

    def SetPositionForMode(self, mode: int) -> None:
        self._mode = int(mode)

    def _add_text(self, text: str, duration_s: float) -> None:
        self._active_texts.append((str(text), time.monotonic() + float(duration_s)))

    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [(t, e) for (t, e) in self._active_texts if e > now]
        if not self._visible and not self._active_texts:
            return None
        return {
            "type": "subtitle",
            "id": self._id,
            "visible": self._visible or bool(self._active_texts),
            "mode": self._mode,
            "lines": [t for (t, _) in self._active_texts],
        }


class SubtitleWindow:
    """SDK-facing class exposing SM_* constants.

    SDK code reads App.SubtitleWindow.SM_TACTICAL etc.; the actual instances
    are _SubtitleWindow. The two are kept separate so the SM_* surface is
    a stable class attribute namespace rather than an instance attribute set.
    """
    SM_BRIDGE         = _SubtitleWindow._SM_BRIDGE
    SM_TACTICAL       = _SubtitleWindow._SM_TACTICAL
    SM_FELIX          = _SubtitleWindow._SM_FELIX
    SM_NONFELIX       = _SubtitleWindow._SM_NONFELIX
    SM_MAP            = _SubtitleWindow._SM_MAP
    SM_CINEMATIC      = _SubtitleWindow._SM_CINEMATIC
    SM_END_CINEMATIC  = _SubtitleWindow._SM_END_CINEMATIC
    SM_SPECIAL_FELIX  = _SubtitleWindow._SM_SPECIAL_FELIX


def SubtitleWindow_Cast(obj):
    """SDK cast helper; returns obj if it walks like a SubtitleWindow else None."""
    if obj is None: return None
    if isinstance(obj, _SubtitleWindow): return obj
    return None
