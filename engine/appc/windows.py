"""Window shims for App.py — TacticalControlWindow, SubtitleWindow, STStylizedWindow.

TacticalControlWindow: event-handler stub until the full menu system lands.
SubtitleWindow: singleton state machine for mission-objective / cinematic
  banner text; snapshotted by SDKMirrorPanel once per tick.
STStylizedWindow: per-instance centred panel (LCARS-framed in BC; dauntless
  re-styles as a modal stack); title + visibility + recorded children.
"""
import time

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
    def SetVisible(self) -> None:
        # Inherited from TGUIObject in the SDK; we flip the same _visible
        # flag used by the BC-specific SetOn. Called by MissionLib.TextBanner.
        self._visible = True
    def IsOn(self) -> bool:     return self._visible

    def SetPositionForMode(self, mode: int, *_extra) -> None:
        # Second positional arg (a "reposition" flag) is used in some Maelstrom
        # missions (e.g. E1M1:2298, E1M2:4916) but has no meaning in dauntless.
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


# ── STStylizedWindow ────────────────────────────────────────────────────────
# Centred LCARS-framed content panel in BC; dauntless re-styles as a centred
# modal panel via #sdk-stylized-stack. SDK pixel coords (parent/x/y/w/h) are
# accepted at the factory but ignored at render time — slot CSS decides layout.

class _STStylizedWindow:
    _counter = 0  # class-level; reset by top_window.reset_for_tests()

    def __init__(self, title: str = ""):
        type(self)._counter += 1
        self._id = f"stylized-{type(self)._counter}"
        self._title = str(title)
        self._visible = True
        self._children: list = []
        self._handler_registrations: list[tuple[int, str]] = []

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append(child)

    def SetVisible(self) -> None:    self._visible = True
    def SetNotVisible(self) -> None: self._visible = False

    def GetObjID(self) -> int:
        # SDK identity hook used in profile (3 missions × 108 calls).
        return id(self)

    def AddPythonFuncHandlerForInstance(self, event_type, qualified_name, *_extra) -> None:
        # Inherited from TGEventHandlerObject; SDK records per-instance
        # handlers (e.g. menu button → mission-init callback). v1 does
        # not dispatch through these — the future SDK→Python click spec
        # will consume _handler_registrations like _TopWindow does.
        self._handler_registrations.append((int(event_type), str(qualified_name)))

    def InteriorChangedSize(self, *_args) -> None:
        # Inherited from TGPane; SDK fires this after AddChild in some
        # layout flows. Dauntless re-styles via slot CSS so no layout
        # propagation is needed — accept and ignore.
        pass

    def SetNoFocus(self) -> None:
        # Inherited from TGUIObject; disables keyboard focus traversal for
        # this pane. Dauntless has no focus system yet — accept and ignore.
        pass

    def _snapshot(self) -> dict:
        return {
            "type": "stylized",
            "id": self._id,
            "visible": self._visible,
            "title": self._title,
        }


def STStylizedWindow_CreateW(title="", *_extra) -> _STStylizedWindow:
    """SDK signature: STStylizedWindow_CreateW(title, parent, x, y, w, h, …).
    All args after the title are accepted and ignored — dauntless re-styles
    via slot CSS rather than SDK pixel coords."""
    return _STStylizedWindow(title)
