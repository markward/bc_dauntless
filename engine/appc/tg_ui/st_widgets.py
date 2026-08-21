"""ST stylized widgets — headless subclasses of the characters.py menu
primitives plus the SortedRegionMenu module-function registry.

Warp/set-course *behaviour* is out of scope (spec non-goal); these classes
exist so Bridge/*MenuHandlers.CreateMenus() completes with real objects.
"""
from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.windows import _STStylizedWindow


class STCharacterMenu(STMenu):
    """Crew-interaction submenu (Hail list, character dialog root)."""

    def __init__(self, label: str = ""):
        super().__init__(label)
        self._sub_pane: "STSubPane | None" = None

    def GetSubPane(self) -> "STSubPane":
        # SDK TacticalMenuHandlers.CreateOrdersStatusDisplay:644 calls
        # App.STSubPane_Cast(pPopupMenu.GetSubPane()).SetExpandToFillParent(0)
        # to opt out of the sub-pane's fill-to-parent layout behaviour.
        # Headless: return a stable STSubPane so the cast succeeds.
        if self._sub_pane is None:
            self._sub_pane = STSubPane()
        return self._sub_pane

    def Open(self, *_args) -> None:   pass
    def Close(self, *_args) -> None:  pass
    def GetDesiredSize(self, size_out=None) -> None:
        # TacticalMenuHandlers:673,677: pMenu.GetDesiredSize(kSize)
        # kSize is an App.NiPoint2; set x/y to 0.0 to avoid layout errors.
        if size_out is not None and hasattr(size_out, "x"):
            size_out.x = 0.0
            size_out.y = 0.0

    # ── Sibling traversal ──
    # TacticalMenuHandlers.UpdateOrderMenus/CallFuncOnMenuAndChildren walk
    # g_pTacticsStatusUIMenu/g_pManeuversStatusUIMenu (STCharacterMenu
    # instances built by CreateOrderMenu) with
    # `pChild = pMenu.GetFirstChild(); while pChild: ... pChild =
    # pMenu.GetNextChild(pChild)`. STMenu (the base class) has no
    # GetFirstChild/GetNextChild, so those calls resolved to a truthy
    # TGObject.__getattr__ _Stub and the `while pChild:` loop never
    # terminated (confirmed live: Sub-step 3a probe hung). Mirrors
    # STTargetMenu's identical override in engine/appc/target_menu.py.
    def GetFirstChild(self):
        return self._children[0] if self._children else None

    def GetLastChild(self):
        return self._children[-1] if self._children else None

    def GetNthChild(self, n):
        # TacticalMenuHandlers.GetOrderString:1908 reads the CURRENT order's
        # button via GetNthChild(iIndex) and, when it is disabled, walks from
        # GetFirstChild to the first ENABLED order instead. Without this the
        # lookup fell through to a truthy _Stub, `not pButton.IsEnabled()`
        # was False, and the fallback never ran -- GetTactic()/GetManeuver()
        # kept reporting a tactic UpdateOrderMenus had just disabled. For the
        # two attack orders g_dAIs has no (order, None, None) catch-all, so
        # ChooseAIFromOrders then returned (None, None) and StartPlayerAI
        # bailed at :1838: the tactical officer never engaged.
        #
        # Explicit bounds rather than a bare index: a negative n must be None,
        # not Python's wrap-around to a real button from the other end.
        i = int(n)
        return self._children[i] if 0 <= i < len(self._children) else None

    def GetNextChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i + 1] if i + 1 < len(self._children) else None

    def GetPrevChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i - 1] if i > 0 else None


class STToggle(STButton):
    """Two-state button (on/off). State sink in Phase 2 headless tier."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._toggled = False

    def SetToggled(self, *args) -> None:    self._toggled = True
    def SetNotToggled(self, *args) -> None: self._toggled = False
    def IsToggled(self) -> int:             return 1 if self._toggled else 0
    def GetToggleState(self) -> int:        return self.IsToggled()


# Where the player drops out of warp when a mission has not said otherwise.
# BC names it in LinkMenuToPlacement's own docstring (MissionLib.py:2636):
# "Links one of the helm menu buttons to a placement other than the default
# 'Player Start'." Every Systems/*/<name>.py placement file defines one.
DEFAULT_ARRIVAL_PLACEMENT = "Player Start"


class STWarpButton(STButton):
    """Warp trigger button — stores config; warp execution is a follow-up."""

    def __init__(self, label: str = "", event=None, flags: int = 0):
        super().__init__(label, event, flags)
        self._warp_time = 0.0
        self._course_menu = None
        self._destination = None
        self._placement_name = DEFAULT_ARRIVAL_PLACEMENT

    def SetWarpTime(self, t) -> None:     self._warp_time = float(t)
    def GetWarpTime(self) -> float:       return self._warp_time
    def SetCourseMenu(self, m) -> None:   self._course_menu = m
    def GetCourseMenu(self):              return self._course_menu
    # Destination is read in SDK truth-branches and string comparisons
    # (BridgeHandlers.py:1409, E6M1/E6M5/E7M6 warp handlers) — must be a
    # real falsy default, never a truthy _Stub.
    def SetDestination(self, dest) -> None:  self._destination = dest
    def GetDestination(self):                return self._destination

    # Where THIS course drops the player out of warp. Real published surface
    # (sdk/.../App.py:8738 STWarpButton_SetPlacementName). The button is the
    # carrier: the course menu owns the mission's choice, the button holds it
    # from the moment a course is set until the warp actually runs.
    def SetPlacementName(self, name) -> None:
        self._placement_name = (str(name) if name
                                else DEFAULT_ARRIVAL_PLACEMENT)

    def GetPlacementName(self) -> str:
        return self._placement_name


class SortedRegionMenu(STMenu):
    """Set-course region list. Sorting/pause flags recorded, unused.

    `region` is the SDK region-module string (e.g. "Systems.Vesuvi.Vesuvi4")
    passed as the 2nd arg of SortedRegionMenu_CreateW — the warp destination
    module. Retained so the offline catalog baker can record it.
    """

    def __init__(self, label: str = "", region=None):
        super().__init__(label)
        self._pause_sorting = 0
        self._region = str(region) if region is not None else None
        self._placement_name = DEFAULT_ARRIVAL_PLACEMENT

    def GetRegionModule(self):
        return self._region

    # A mission's override of where this destination drops the player out of
    # warp. Real published surface (sdk/.../App.py:8763/:8769), and the sole
    # target of MissionLib.LinkMenuToPlacement — which E1M1.py:673 uses to move
    # the Starbase 12 arrival from "Player Start" (93 km from the mission's own
    # nav point) out to "PlayerSpecialStart" (312 km), far enough that the
    # scripted in-system-warp approach has somewhere to run. Unimplemented this
    # was a silent _Stub: heatmap rank 144, 57 hits over 56/233 runs.
    def SetPlacementName(self, name) -> None:
        self._placement_name = (str(name) if name
                                else DEFAULT_ARRIVAL_PLACEMENT)

    def GetPlacementName(self) -> str:
        return self._placement_name

    def ClearInfo(self, *args) -> None:
        # Region-info reset on set-course rebuild (Systems/Utils.py:70).
        pass


class STRoundedButton(STButton):
    pass


class STSubPane(TGPane):
    def SetExpandToFillParent(self, *_args) -> None:
        # TacticalMenuHandlers:644 opts out of fill-to-parent layout.
        pass

    def GetButtonW(self, label) -> "STButton | None":
        """Child button by label, or None when absent.

        SWIG declares GetButtonW on STSubPane itself, not on TGPane
        (sdk/Build/scripts/App.py:7781), and wraps the result as
        `if val: val = STButtonPtr(val)` -- a NULL button stays falsy, so
        None-when-absent is the faithful contract (same as STMenu.GetButtonW).

        QuickBattle builds the AI Level selector as a bare STSubPane
        (QuickBattle.py:1587) and drives the Low/Medium/High radio state
        through `g_pAIMenu.GetButtonW(label).SetChosen(n)` (:2485-2487,
        :2545-2555). Without this override the lookup fell through
        TGObject.__getattr__ to a truthy _Stub and every SetChosen was a
        silent no-op.

        Linear scan over TGPane's `_children` rather than a parallel
        label->button dict: STSubPane children arrive through the inherited
        TGPane.AddChild/InsertChild/DeleteChild, so a second registry would be
        a duplicate source of truth that those three would have to maintain.
        Menus stay in the single digits.
        """
        key = str(label)
        for child, _x, _y in self._children:
            if isinstance(child, STButton) and child.GetLabel() == key:
                return child
        return None


# ── Module-level registry (SDK: SortedRegionMenu_* module functions) ─────────

_warp_button: "STWarpButton | None" = None
_pause_sorting: int = 0


def _reset_module_state() -> None:
    """Test-only — clear module registry between tests."""
    global _warp_button, _pause_sorting
    _warp_button = None
    _pause_sorting = 0


def SortedRegionMenu_SetWarpButton(button) -> None:
    global _warp_button
    _warp_button = button


def SortedRegionMenu_GetWarpButton():
    return _warp_button


def SortedRegionMenu_SetPauseSorting(flag) -> None:
    global _pause_sorting
    _pause_sorting = int(flag)


def SortedRegionMenu_ClearSetCourseMenu(*args) -> None:
    pass


def SortedRegionMenu_IsSortingPaused() -> int:
    # Systems/Utils.py:32 branches on `if not bPaused:` — must return the
    # real flag, not a truthy stub.
    return _pause_sorting


# ── Factories ────────────────────────────────────────────────────────────────

def STCharacterMenu_CreateW(label="", *_extra) -> STCharacterMenu:
    return STCharacterMenu(str(label))


def STWarpButton_CreateW(label="", event=None, flags=0) -> STWarpButton:
    return STWarpButton(str(label), event, flags)


def STToggle_CreateW(label="", default=0, label_on="", event_on=None,
                     label_off="", event_off=None, *_extra) -> STToggle:
    """SDK signature (BridgeUtils.py:76): STToggle_CreateW(pName, iDefault,
    pNameOn, pOnEvent, pNameOff, pOffEvent)."""
    t = STToggle(str(label), event_on)
    t._label_on = str(label_on)
    t._label_off = str(label_off)
    t._event_on = event_on
    t._event_off = event_off
    if default:
        t.SetToggled()
    return t


def SortedRegionMenu_CreateW(label="", region=None, *_extra) -> SortedRegionMenu:
    return SortedRegionMenu(str(label), region)


def STRoundedButton_CreateW(label="", event=None, flags=0, *_extra) -> STRoundedButton:
    # SDK QuickBattle.CreateBridgeMenuButton calls this as
    # STRoundedButton_CreateW(pName, pEvent, fWidth, fHeight) — width/height are
    # layout-only and ignored headless (absorbed by *_extra, with the existing
    # 3-arg flags form still honoured for other call sites).
    return STRoundedButton(str(label), event, flags if not _extra else 0)


def STSubPane_Create(*args) -> STSubPane:
    return STSubPane()


# ── Strict-ish casts (None for wrong type — SDK null-guards these) ───────────

def STButton_Cast(obj):
    return obj if isinstance(obj, STButton) else None


def STStylizedWindow_Cast(obj):
    return obj if isinstance(obj, _STStylizedWindow) else None


def STRoundedButton_Cast(obj):
    return obj if isinstance(obj, STRoundedButton) else None


def STSubPane_Cast(obj):
    return obj if isinstance(obj, STSubPane) else None


def STToggle_Cast(obj):
    return obj if isinstance(obj, STToggle) else None


def STWarpButton_Cast(obj):
    return obj if isinstance(obj, STWarpButton) else None


def SortedRegionMenu_Cast(obj):
    """Lenient pass-through, same rationale as characters.STMenu_Cast:
    SDK chains the result without null-guarding (Systems/Utils.py:70
    `pSystemMenu.ClearInfo()`, MissionLib.py:2613 `assert pMenu`), and the
    input is often a plain STMenu auto-vivified by GetSubmenuW. Real
    SortedRegionMenus cast cleanly; other objects flow through so their
    TGObject stub-__getattr__ absorbs the follow-up calls."""
    if isinstance(obj, SortedRegionMenu):
        return obj
    if obj is None:
        return None
    return obj
