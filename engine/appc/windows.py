"""Window shims for App.py — TacticalControlWindow, SubtitleWindow, STStylizedWindow.

TacticalControlWindow: event-handler stub until the full menu system lands.
SubtitleWindow: singleton state machine for mission-objective / cinematic
  banner text; snapshotted by SDKMirrorPanel once per tick.
STStylizedWindow: per-instance centred panel (LCARS-framed in BC; dauntless
  re-styles as a modal stack); title + visibility + recorded children.
"""
import time

from engine.appc.events import TGEventHandlerObject
from engine.appc.tg_ui.widgets import TGPane

# Pane-index constants, mirrored from the SDK module
# Tactical/Interface/TacticalControlWindow.py so host-side layout invocation
# reads the same slots the SDK does. Only the two we use are defined here.
INTERFACE_PANE = 0   # TacticalControlWindow.GetNthChild(INTERFACE_PANE)
TACTICAL_MENU = 0    # interfacePane.GetNthChild(TACTICAL_MENU) -> officer-menu window


class TacticalControlWindow(TGEventHandlerObject):
    _instance: "TacticalControlWindow | None" = None

    def __init__(self):
        super().__init__()
        self._radar_display = None
        self._children: list = []      # (child, x, y) — recorded, not rendered
        self._menus: list = []         # STTopLevelMenu roots, in add order
        self._tactical_menu = None

    @classmethod
    def GetInstance(cls) -> "TacticalControlWindow":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # CallNextHandler is inherited from TGEventHandlerObject (advances the LIFO
    # instance-handler chain). Previously a no-op, which silently dropped
    # chain propagation.

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def AddMenuToList(self, menu) -> None:
        if menu not in self._menus:
            self._menus.append(menu)

    def GetMenuList(self) -> list:
        return list(self._menus)

    def FindMenu(self, label):
        """Menu lookup by label. SDK: 66 call sites, all null-guarded with
        `if pMenu:` — None for a missing label is the faithful contract."""
        key = str(label)
        for menu in self._menus:
            if menu.GetLabel() == key:
                return menu
        return None

    def GetMenuParentPane(self, label):
        """The AddChild-recorded pane whose subtree holds the labelled menu.
        SDK: LoadBridge.py:155, guarded `if pPane != None:`.

        For most menus (Science, XO, Helm, Engineer) the menu's containing
        STStylizedWindow is a direct AddChild of the TCW.  For Tactical the
        pane is nested one level deeper inside kInterfacePane; search
        recursively up to 2 levels so both layouts are covered.
        """
        menu = self.FindMenu(label)
        if menu is None:
            return None

        def _contains_menu(container, target_menu, depth):
            """Return the container if target_menu is a direct child, else None."""
            # __dict__ read — TGObject.__getattr__ returns a truthy _Stub
            # for missing attributes (never the getattr default), and
            # iterating a _Stub is infinite (__getitem__ yields stubs for
            # every index). STButton has no _children; this must yield [].
            children = container.__dict__.get("_children", [])
            for item in children:
                # TGPane stores tuples (child, x, y); _STStylizedWindow/STMenu
                # stores plain objects.
                child = item[0] if isinstance(item, tuple) else item
                if child is target_menu:
                    return container
                if depth > 0:
                    result = _contains_menu(child, target_menu, depth - 1)
                    if result is not None:
                        return result
            return None

        for (child, _x, _y) in self._children:
            found = _contains_menu(child, menu, depth=2)
            if found is not None:
                return found
        return None

    def SetTacticalMenu(self, menu) -> None:
        # Engine-internal in original BC (Appc binding has no Python
        # caller); our LoadBridge.CreateCharacterMenus stands in.
        self._tactical_menu = menu

    def GetTacticalMenu(self):
        return self._tactical_menu

    # Radar display accessor — SDK TacticalMenuHandlers.CreateRadarDisplay
    # at sdk/Build/scripts/Bridge/TacticalMenuHandlers.py:475 calls
    # pTacticalWindow.SetRadarDisplay(p); RadarDisplay.py:55 calls
    # pTCW.GetRadarDisplay() to get it back.
    def SetRadarDisplay(self, p) -> None:
        self._radar_display = p

    def GetRadarDisplay(self):
        return self._radar_display

    # ── Additional state sinks for TacticalMenuHandlers.CreateMenus() ────────
    # These accessors are recorded for future use by the tactical interface
    # but have no effect in the headless bridge-menu build phase.
    def SetTargetMenu(self, p) -> None:
        self._target_menu = p

    def GetTargetMenu(self):
        return getattr(self, "_target_menu", None)

    def SetShipDisplay(self, p) -> None:
        self._ship_display = p

    def GetShipDisplay(self):
        return getattr(self, "_ship_display", None)

    def SetEnemyShipDisplay(self, p) -> None:
        self._enemy_ship_display = p

    def GetEnemyShipDisplay(self):
        return getattr(self, "_enemy_ship_display", None)

    def SetWeaponsDisplay(self, p) -> None:
        self._weapons_display = p

    def GetWeaponsDisplay(self):
        return getattr(self, "_weapons_display", None)

    def SetWeaponsControl(self, p) -> None:
        self._weapons_control = p

    def GetWeaponsControl(self):
        return getattr(self, "_weapons_control", None)

    def SetRadarToggle(self, p) -> None:
        self._radar_toggle = p

    def GetRadarToggle(self):
        return getattr(self, "_radar_toggle", None)

    def SetMousePickFire(self, v) -> None:
        self._mouse_pick_fire = bool(v)

    def GetMousePickFire(self) -> int:
        return 1 if getattr(self, "_mouse_pick_fire", False) else 0

    def GetNthChild(self, n):
        n = int(n)
        if 0 <= n < len(self._children):
            return self._children[n][0]
        return None

    def GetParent(self):
        return None

    def IsVisible(self) -> int:
        return 1

    def Layout(self, *_args) -> None:
        """Run the layout resolver over the interface pane's direct children.

        The SDK's Tactical/Interface/TacticalControlWindow.RepositionUI() ends
        with ``pTacCtrlWindow.Layout()`` to cascade the recorded SetPosition/
        AlignTo placements into absolute rects. In real BC the TCW is a TGPane
        and Layout() lays out its whole subtree; here the TCW is a plain
        event-handler object, so we drive the resolver explicitly.

        We lay out only the interface pane's *direct* children (that is all the
        officer-menu window — TACTICAL_MENU=0 — and the downstream tasks need),
        each resolved independently: several interface children AlignTo display
        widgets (RadarDisplay, ShipDisplay) that never opt into resolver state,
        so a single unresolvable AlignTo must NOT abort its siblings. We reuse
        the TGPane resolver's own _resolve_child_rect; we do not recurse into
        the stylized-window menu subtrees (their children are STMenu/STButton,
        not positioned resolver panes).
        """
        from engine.appc.tg_ui.layout import Rect, LayoutNotResolved

        ipane = self.GetNthChild(INTERFACE_PANE)
        if not isinstance(ipane, TGPane):
            return
        ipane._ensure_layout_state()
        if ipane._abs_rect is None:            # interface pane is the layout root
            ipane._abs_rect = Rect(ipane._local_left, ipane._local_top,
                                   ipane._width, ipane._height)
        origin_l = ipane._abs_rect.left
        origin_t = ipane._abs_rect.top
        for child, _x, _y in ipane._children:
            if not isinstance(child, TGPane):  # display widgets: not resolver panes
                continue
            child._ensure_layout_state()
            try:
                child._abs_rect = ipane._resolve_child_rect(child, origin_l, origin_t)
            except LayoutNotResolved:
                # AlignTo target isn't a laid-out resolver widget (e.g. a radar/
                # ship display). Leave this child unresolved (GetScreenOffset
                # stays fail-loud for it) and keep placing its siblings.
                continue



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
        # Single replaceable crew-speech slot (speaker, text, expiry). Separate
        # from _active_texts so a SpeakLine preemption is a clean replacement
        # and never collides with a mission banner. Owned by CrewSpeechBus.
        self._crew_line: tuple[str, str, float] | None = None

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

    def set_crew_line(self, speaker: str, text: str, duration: float) -> None:
        # Replaces the crew slot wholesale -- preemption == replacement.
        self._crew_line = (
            str(speaker), str(text), time.monotonic() + float(duration),
        )

    def clear_crew_line(self) -> None:
        # Skip (Backspace) cuts the line short: drop the subtitle immediately
        # instead of letting it dwell to its original expiry.
        self._crew_line = None

    def _add_text(self, text: str, duration_s: float) -> None:
        self._active_texts.append((str(text), time.monotonic() + float(duration_s)))

    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [(t, e) for (t, e) in self._active_texts if e > now]
        if self._crew_line is not None and self._crew_line[2] <= now:
            self._crew_line = None
        has_crew = self._crew_line is not None
        if not self._visible and not self._active_texts and not has_crew:
            return None
        snap = {
            "type": "subtitle",
            "id": self._id,
            "visible": self._visible or bool(self._active_texts) or has_crew,
            "mode": self._mode,
            "lines": [t for (t, _) in self._active_texts],
        }
        if has_crew:
            snap["speaker"] = self._crew_line[0]
            snap["speech"] = self._crew_line[1]
        return snap


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


# ── OptionsWindow ───────────────────────────────────────────────────────────

class _OptionsWindow:
    """Never-visible stand-in for BC's Options main window.

    In real BC the Options main window always exists in the Appc UI hierarchy,
    so SDK code dereferences FindMainWindow(MWT_OPTIONS) without a None check —
    Bridge/HelmMenuHandlers.ObjectEnteredSet:407 crashed on warp set-entry when
    our _TopWindow returned None. Dauntless renders no SDK Options window
    (options live in the CEF configuration panel), so it is never visible:
    returning 0 from IsCompletelyVisible both avoids the None crash and enables
    the SDK "Entering <system>" banner, which is gated on
    ``pOptions.IsCompletelyVisible() == 0``.

    Plain class, no __getattr__ catch-all — matching _TopWindow's philosophy
    that unimplemented methods should raise loudly, not silently no-op.
    """

    def IsCompletelyVisible(self) -> int:
        return 0

    def IsVisible(self) -> int:
        return 0


# ── CinematicWindow ─────────────────────────────────────────────────────────

class _CinematicWindow(TGEventHandlerObject):
    """Never-visible stand-in for BC's Cinematic main window.

    Same rationale as _OptionsWindow just above: in real BC the Cinematic
    main window always exists in the Appc UI hierarchy, so SDK code
    dereferences FindMainWindow(MWT_CINEMATIC) without a None check.
    AI/Compound/DockWithStarbase.SetupCutscene does exactly that:

        pFocus = pTopWindow.GetFocus()
        pCinematic = pTopWindow.FindMainWindow(App.MWT_CINEMATIC)
        if (not pFocus) or (pFocus.GetObjID() != pCinematic.GetObjID()):

    `or` short-circuits on `not pFocus`, so this was silent as long as
    GetFocus() was always None — but Bridge/XOMenuHandlers.ShowLog (wired
    live via LoadBridge.Load -> XOMenuHandlers.CreateMenus, the "Show
    Mission Log" XO-menu button) calls pTopWindow.SetFocus(pLog) and never
    clears it, so any later dock crashed with
    AttributeError: 'NoneType' object has no attribute 'GetObjID'
    once FindMainWindow(MWT_CINEMATIC) returned raw None.

    Inherits TGEventHandlerObject (-> TGObject) purely for a real,
    stable GetObjID() and the catch-all __getattr__ safety net.

    IsWindowActive/IsInteractive are given explicit, BC-faithful normal-
    state answers rather than being left to the truthy _Stub catch-all:
    several SDK sites call FindMainWindow(MWT_CINEMATIC) WITHOUT a None
    guard and then query these methods directly in an OR-guard (e.g.
    Bridge/TacticalInterfaceHandlers.GotFocus, MissionLib.ExitGame) —
    a truthy stub for IsWindowActive() silently flips those guards.
    """

    def IsWindowActive(self):
        return 0

    def IsInteractive(self):
        return 1


class _MainViewWindow(TGEventHandlerObject):
    """Never-composited stand-in for BC's MWT_BRIDGE / MWT_TACTICAL main windows.

    Real BC always has both; SDK UI code re-parents the TacticalControlWindow
    into whichever one is visible and dereferences the result with no None
    guard. Tactical.Interface.TacticalControlWindow.Refresh does exactly that:

        elif pTop.IsTacticalVisible():
            pTacticalWindow = pTop.FindMainWindow(App.MWT_TACTICAL)
            pTacticalWindow.AddChild(pTacCtrlWindow, 0.0, 0.0, 0)

    Returning raw None there crashed FinishedUndocking at the end of the E6M2
    dock (AttributeError: 'NoneType' has no attribute 'AddChild'). Same class of
    gap as _CinematicWindow / _OptionsWindow.

    Deliberately NOT a BridgeWindow/TacticalWindow/TGPane, so the cast-guarded
    SDK sites (BridgeWindow_Cast/TacticalWindow_Cast/TGPane_Cast(FindMainWindow(
    ...))) still resolve None and skip exactly as they did when the whole window
    was None — no new code paths are activated. Only the direct-AddChild sites
    are fixed. AddChild/RemoveChild record children (like the TCW); visibility is
    a tracked no-op; IsWindowActive answers the BC normal-state value so a truthy
    _Stub can't flip an OR-guard (see _CinematicWindow)."""

    def __init__(self):
        super().__init__()
        self._children: list = []
        self._visible = True

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def RemoveChild(self, child, *_extra) -> None:
        self._children = [c for c in self._children if c[0] is not child]

    def SetVisible(self, *_a) -> None:
        self._visible = True

    def SetNotVisible(self, *_a) -> None:
        self._visible = False

    def IsVisible(self) -> int:
        return 1 if self._visible else 0

    def IsWindowActive(self):
        return 0


# ── STStylizedWindow ────────────────────────────────────────────────────────
# Centred LCARS-framed content panel in BC; dauntless re-styles as a centred
# modal panel via #sdk-stylized-stack. SDK pixel coords (parent/x/y/w/h) are
# accepted at the factory but ignored at render time — slot CSS decides layout.

class _STStylizedWindow(TGPane):
    """LCARS-framed content panel.

    Inherits TGPane so that TGPane_Cast(an_STStylizedWindow) succeeds,
    matching the real SDK hierarchy where STStylizedWindow(TGWindow(TGPane)).
    sdk/Build/scripts/App.py:7604 — class STStylizedWindow(TGWindow) where
    TGWindow(TGPane) at line 1805.

    _STStylizedWindow overrides all geometry, child-access, and visibility
    methods from TGPane with its own implementations, so inheriting TGPane
    is purely for IS-A correctness; no TGPane behaviour leaks through.
    Children are stored as bare objects (not (child, x, y) tuples) to match
    the original _STStylizedWindow contract; GetNthChild/GetFirstChild etc.
    are overridden accordingly.
    """
    _counter = 0  # class-level; reset by top_window.reset_for_tests()

    def __init__(self, title: str = ""):
        super().__init__()   # TGPane.__init__ — initialises _children=[], etc.
        type(self)._counter += 1
        self._id = f"stylized-{type(self)._counter}"
        self._title = str(title)
        self._visible = True
        self._children: list = []       # bare children (not (child,x,y) tuples)
        self._handler_registrations: list[tuple[int, str]] = []
        self._max_w: float = 0.0
        self._max_h: float = 0.0
        # Lazy interior/exterior panes — allocated on first access so the
        # (common) case of never calling these methods stays lightweight.
        self._interior_pane: "TGPane | None" = None
        self._exterior_pane: "TGPane | None" = None
        self._name_paragraph: "TGParagraph | None" = None

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append(child)

    def SetVisible(self, *_args) -> None:    self._visible = True
    def SetNotVisible(self, *_args) -> None: self._visible = False

    def GetObjID(self) -> int:
        # SDK identity hook used in profile (3 missions × 108 calls).
        return id(self)

    def AddPythonFuncHandlerForInstance(self, event_type, qualified_name, *_extra) -> None:
        # Inherited from TGEventHandlerObject; SDK records per-instance
        # handlers (e.g. menu button → mission-init callback). v1 does
        # not dispatch through these — the future SDK→Python click spec
        # will consume _handler_registrations like _TopWindow does.
        self._handler_registrations.append((int(event_type), str(qualified_name)))

    def ProcessEvent(self, event) -> None:
        # The base TGEventHandlerObject.ProcessEvent dispatches from _handlers,
        # but this class records handlers in _handler_registrations (kept as the
        # introspection surface for the future click-dispatch spec). Dispatch
        # from that list so the Close button's ET_INPUT_CLOSE_MENU event reaches
        # MissionLib.CloseInfoBox + the mission's own handler.
        from engine.appc.events import _resolve_handler
        etype = event.GetEventType()
        for reg_type, qualified_name in list(self._handler_registrations):
            if reg_type != etype:
                continue
            fn = _resolve_handler(qualified_name)
            if fn is not None:
                fn(self, event)

    def InteriorChangedSize(self, *_args) -> None:
        # Inherited from TGPane; SDK fires this after AddChild in some
        # layout flows. Dauntless re-styles via slot CSS so no layout
        # propagation is needed — accept and ignore.
        pass

    def SetNoFocus(self, *_args) -> None:
        # Inherited from TGUIObject; disables keyboard focus traversal for
        # this pane. Dauntless has no focus system yet — accept and ignore.
        pass

    # ── Geometry (headless: all 0.0 — no real pixel layout) ─────────────────
    def GetWidth(self) -> float:             return 0.0
    def GetHeight(self) -> float:            return 0.0
    def GetBorderWidth(self) -> float:       return 0.0
    def GetBorderHeight(self) -> float:      return 0.0
    def GetMaximumWidth(self) -> float:      return self._max_w
    def GetMaximumHeight(self) -> float:     return self._max_h
    # Interior-size variants used by TacticalControlWindow.ResizeUI to size
    # child menus to the available interior area (width minus frame borders).
    # Headless: same as the outer maximum since we have no rendered borders.
    def GetMaximumInteriorWidth(self) -> float:  return self._max_w
    def GetMaximumInteriorHeight(self) -> float: return self._max_h
    def Resize(self, *_args) -> None:        pass
    def ResizeUI(self, *_args) -> None:      pass
    def RepositionUI(self, *_args) -> None:  pass
    def Layout(self, *_args) -> None:        pass
    def ResizeToContents(self, *_args) -> None: pass

    def SetMaximumSize(self, w, h) -> None:
        # TacticalMenuHandlers / EngineerMenuHandlers use this to cap layout;
        # headless stores the values for potential introspection.
        self._max_w = float(w) if not isinstance(w, type(None)) else 0.0
        self._max_h = float(h) if not isinstance(h, type(None)) else 0.0
        # The layout resolver reads a widget's box from the _width/_height
        # attributes (TGPane._resolve_child_rect). A stylized window has no
        # separate laid-out size — for the fixed tactical-menu window its
        # on-screen box IS its maximum size — so mirror it here. The SDK-facing
        # GetWidth()/GetHeight() stay 0.0 (BC pixel geometry we never render);
        # only the resolver-input attributes are populated.
        self._width = self._max_w
        self._height = self._max_h

    def SetFixedSize(self, *_args) -> None:  pass
    def AlignTo(self, *_args) -> None:       pass  # layout-relative positioning; no-op headless
    def SetPosition(self, *_args) -> None:   pass
    def SetLeft(self, *_args) -> None:       pass
    def SetTop(self, *_args) -> None:        pass
    def GetLeft(self) -> float:              return 0.0
    def GetTop(self) -> float:              return 0.0

    # ── Child access ─────────────────────────────────────────────────────────
    def GetFirstChild(self):
        return self._children[0] if self._children else None

    def GetLastChild(self):
        return self._children[-1] if self._children else None

    def GetNextChild(self, child):
        try:
            idx = self._children.index(child)
            return self._children[idx + 1] if idx + 1 < len(self._children) else None
        except ValueError:
            return None

    def GetPrevChild(self, child):
        try:
            idx = self._children.index(child)
            return self._children[idx - 1] if idx > 0 else None
        except ValueError:
            return None

    def GetNthChild(self, n):
        n = int(n)
        return self._children[n] if 0 <= n < len(self._children) else None

    def KillChildren(self) -> None:
        self._children.clear()
        self._interior_pane = None

    # ── Interior/exterior pane (LCARS frame structure) ───────────────────────
    # BC's STStylizedWindow wraps a content pane (interior) and a decorative
    # frame pane (exterior).  Headless: interior = self (children live here),
    # exterior = an empty TGPane (glass-icon queries return None → no-ops).
    def GetInteriorPane(self):
        if self._interior_pane is None:
            self._interior_pane = _STStylizedWindowInterior(self)
        return self._interior_pane

    def GetExteriorPane(self):
        if self._exterior_pane is None:
            # EngineerMenuHandlers gets three glass TGIcons via GetLastChild /
            # GetPrevChild, then calls SetColor / SetIconNum on each.  Pre-populate
            # the exterior pane with three TGIcon stubs so TGIcon_Cast returns a real
            # object and those calls succeed as state-sinks.
            from engine.appc.tg_ui.widgets import TGPane, TGIcon  # lazy — avoids circular import
            p = TGPane()
            for _ in range(3):
                p.AddChild(TGIcon())
            self._exterior_pane = p
        return self._exterior_pane

    def GetNameParagraph(self):
        # EngineerMenuHandlers changes the power-window title font/color.
        if self._name_paragraph is None:
            from engine.appc.tg_ui.widgets import TGParagraph  # lazy — avoids circular import
            self._name_paragraph = TGParagraph(self._title)
        return self._name_paragraph

    # ── Focus / visibility ────────────────────────────────────────────────────
    def SetFocus(self, *_args) -> None:                pass
    def SetUseFocusGlass(self, *_args) -> None:        pass
    def SetUseScrolling(self, *_args) -> None:         pass
    def SetNotMinimized(self, *_args) -> None:         pass
    def SetEnabled(self, *_args) -> None:              pass
    def IsVisible(self) -> int:                        return 1 if self._visible else 0
    def IsEnabled(self) -> int:                        return 1

    # ── Containing-window linkage (bridge menus ask menus for their window) ──
    # STButton / STMenu call GetContainingWindow() to find their host frame.
    # Headless: the stylized window IS the containing window.
    def GetContainingWindow(self): return self
    def GetConceptualParent(self):  return self
    def GetParent(self):
        # EngineerMenuHandlers line 55: GetInteriorPane().GetParent().SetNotBatchChildPolys()
        return _NullBatchPane()

    def SetNotBatchChildPolys(self, *_args) -> None:   pass

    def _snapshot(self) -> dict:
        return {
            "type": "stylized",
            "id": self._id,
            "visible": self._visible,
            "title": self._title,
        }


class _STStylizedWindowInterior:
    """Proxy that forwards child operations back to the owning STStylizedWindow.

    BC's interior pane IS the content area — AddChild calls on the interior
    and on the stylized window itself should see the same child list.
    Uses duck-typing so no TGPane import is needed at class-definition time.
    """

    def __init__(self, owner: "_STStylizedWindow"):
        self._owner = owner

    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._owner.AddChild(child, x, y)

    def GetFirstChild(self):
        return self._owner.GetFirstChild()

    def GetNextChild(self, child):
        return self._owner.GetNextChild(child)

    def GetParent(self):
        return _NullBatchPane()

    def SetNotBatchChildPolys(self, *_args) -> None:
        pass


class _NullBatchPane:
    """Minimal pane returned by GetParent() so SetNotBatchChildPolys no-ops."""
    def SetNotBatchChildPolys(self, *_args) -> None: pass
    def SetVisible(self, *_args) -> None:            pass
    def SetNotVisible(self, *_args) -> None:         pass
    def IsVisible(self) -> int:                      return 0


def STStylizedWindow_CreateW(title="", *_extra) -> _STStylizedWindow:
    """SDK signature: STStylizedWindow_CreateW(title, parent, x, y, w, h, …).
    All args after the title are accepted and ignored — dauntless re-styles
    via slot CSS rather than SDK pixel coords."""
    return _STStylizedWindow(title)
